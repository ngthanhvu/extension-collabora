"""Offline Auto Furigana macro for Collabora Office Writer."""

from pathlib import Path
import hashlib
import functools
import re
import sys

import uno
import unohelper
from com.sun.star.frame import XStatusListener
from com.sun.star.awt import XActionListener


def _find_vendor():
    """Locate bundled modules when Collabora's script provider omits __file__."""
    roots = (
        Path.home() / ".config/collaboraoffice/4/user/uno_packages/cache/uno_packages",
        Path.home() / ".config/libreoffice/4/user/uno_packages/cache/uno_packages",
        Path("/opt/collaboraoffice/share/uno_packages/cache/uno_packages"),
        Path("/usr/lib/libreoffice/share/uno_packages/cache/uno_packages"),
    )
    for root in roots:
        if not root.is_dir():
            continue
        matches = list(root.glob("*/AutoFurigana-*.oxt/pythonpath"))
        if matches:
            return matches[-1]
    raise ImportError("Cannot find AutoFurigana extension pythonpath")


VENDOR = _find_vendor()
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from pykakasi import kakasi  # noqa: E402


KANJI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CONVERTER = None


class _CommandStatus(unohelper.Base, XStatusListener):
    def __init__(self):
        self.state = None

    def statusChanged(self, event):
        self.state = event.State

    def disposing(self, _event):
        pass


class _GuidePager(unohelper.Base, XActionListener):
    """Page through long selections without losing edited ruby readings."""

    def __init__(self, dialog, rows, page_size):
        self.dialog = dialog
        self.rows = rows
        self.page_size = page_size
        self.page = 0

    @property
    def page_count(self):
        return max(1, (len(self.rows) + self.page_size - 1) // self.page_size)

    def _save(self):
        start = self.page * self.page_size
        for slot in range(self.page_size):
            index = start + slot
            if index >= len(self.rows):
                break
            self.rows[index][1] = self.dialog.getControl(
                "ruby_{}".format(slot)
            ).getText().strip()

    def show(self):
        start = self.page * self.page_size
        current = self.rows[start:start + self.page_size]
        for slot in range(self.page_size):
            base = self.dialog.getControl("base_{}".format(slot))
            ruby = self.dialog.getControl("ruby_{}".format(slot))
            if slot < len(current):
                base.setText(current[slot][0])
                ruby.setText(current[slot][1])
                base.setVisible(True)
                ruby.setVisible(True)
            else:
                base.setVisible(False)
                ruby.setVisible(False)
        self.dialog.getControl("page").setText(
            "{}/{}".format(self.page + 1, self.page_count)
        )
        self.dialog.getControl("previous").setEnable(self.page > 0)
        self.dialog.getControl("next").setEnable(self.page + 1 < self.page_count)
        self.dialog.getControl("ruby_preview").setText(
            "　".join(reading for _base, reading in current)
        )
        self.dialog.getControl("base_preview").setText(
            "　".join(base for base, _reading in current)
        )

    def actionPerformed(self, event):
        self._save()
        if event.ActionCommand == "previous" and self.page > 0:
            self.page -= 1
        elif event.ActionCommand == "next" and self.page + 1 < self.page_count:
            self.page += 1
        self.show()

    def disposing(self, _event):
        pass


def _hide_field_shading(document):
    """Turn off Writer's on-screen ruby shading when its state is available."""
    try:
        frame = document.getCurrentController().getFrame()
        url = uno.getComponentContext().ServiceManager.createInstanceWithContext(
            "com.sun.star.util.URLTransformer", uno.getComponentContext()
        )
        command = uno.createUnoStruct("com.sun.star.util.URL")
        command.Complete = ".uno:FieldShadings"
        url.parseStrict(command)
        dispatch = frame.queryDispatch(command, "", 0)
        listener = _CommandStatus()
        dispatch.addStatusListener(listener, command)
        dispatch.removeStatusListener(listener, command)
        if listener.state is True:
            dispatch.dispatch(command, ())
    except Exception:
        pass


def _message(text, title="Auto Furigana", error=False):
    context = uno.getComponentContext()
    toolkit = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", context
    )
    desktop = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context
    )
    window = desktop.getCurrentFrame().getContainerWindow()
    box_type = 3 if error else 1
    toolkit.createMessageBox(window, box_type, 1, title, text).execute()


def _converter():
    global CONVERTER
    if CONVERTER is None:
        CONVERTER = kakasi()
    return CONVERTER


def _selection(document):
    selected = document.getCurrentController().getSelection()
    if not selected or selected.getCount() != 1:
        return None
    item = selected.getByIndex(0)
    return item if hasattr(item, "getString") else None


def _dictionary_parts(original, reading):
    """Split a word like 漢字 into exact dictionary-backed ruby groups."""
    converter = _converter()
    jconv = converter._kakasi._jconv

    @functools.lru_cache(maxsize=None)
    def solve(base_at, reading_at):
        if base_at == len(original) and reading_at == len(reading):
            return ()
        if base_at >= len(original) or reading_at > len(reading):
            return None

        char = original[base_at]
        candidates = []
        if KANJI.match(char):
            table = jconv._kanwa.load(char) or {}
            for base, values in table.items():
                if not original.startswith(base, base_at):
                    continue
                for yomi, _context in values:
                    if reading.startswith(yomi, reading_at):
                        candidates.append((base, yomi))
        else:
            literal = _converter().convert(char)[0]["hira"]
            if reading.startswith(literal, reading_at):
                candidates.append((char, literal))

        best = None
        for base, yomi in candidates:
            tail = solve(base_at + len(base), reading_at + len(yomi))
            if tail is None:
                continue
            part = ((base_at, len(base), yomi),) + tail
            # Prefer Mono-like output: the greatest number of exact groups.
            if best is None or len(part) > len(best):
                best = part
        return best

    return solve(0, 0)


def _split_kanji_reading(base, reading):
    """Split one all-Kanji group into one editable reading per character."""
    if len(base) <= 1:
        return (reading,)
    jconv = _converter()._kakasi._jconv
    target = max(1.0, len(reading) / len(base))

    @functools.lru_cache(maxsize=None)
    def solve(char_at, reading_at):
        remaining_chars = len(base) - char_at
        remaining_reading = len(reading) - reading_at
        if remaining_chars == 0:
            return (0.0, ()) if remaining_reading == 0 else None
        if remaining_reading < remaining_chars:
            return None

        char = base[char_at]
        candidates = set()
        table = jconv._kanwa.load(char) or {}
        for key, values in table.items():
            if key != char:
                continue
            for yomi, _context in values:
                if reading.startswith(yomi, reading_at):
                    candidates.add(yomi)

        choices = [(value, 20.0) for value in candidates]
        max_length = remaining_reading - (remaining_chars - 1)
        for length in range(1, max_length + 1):
            value = reading[reading_at:reading_at + length]
            choices.append((value, -abs(length - target)))

        best = None
        for value, local_score in choices:
            tail = solve(char_at + 1, reading_at + len(value))
            if tail is None:
                continue
            score = local_score + tail[0]
            result = (score, (value,) + tail[1])
            if best is None or result[0] > best[0]:
                best = result
        return best

    result = solve(0, 0)
    if result is not None:
        return result[1]
    # A reading normally has at least one kana per Kanji; keep a safe fallback.
    return tuple(reading[index:index + 1] for index in range(len(base) - 1)) + (
        reading[len(base) - 1:],
    )


def _segments(text):
    """Return exact Mono-like groups, falling back to a whole-word group."""
    offset = 0
    for token in _converter().convert(text):
        original = token["orig"]
        if KANJI.search(original):
            parts = _dictionary_parts(original, token["hira"])
            if parts:
                for part_offset, length, reading in parts:
                    base = original[part_offset:part_offset + length]
                    if KANJI.search(base):
                        if len(base) > 1 and all(KANJI.match(char) for char in base):
                            char_readings = _split_kanji_reading(base, reading)
                            for index, char_reading in enumerate(char_readings):
                                yield offset + part_offset + index, 1, char_reading
                        else:
                            yield offset + part_offset, length, reading
            else:
                if len(original) > 1 and all(KANJI.match(char) for char in original):
                    for index, char_reading in enumerate(
                        _split_kanji_reading(original, token["hira"])
                    ):
                        yield offset + index, 1, char_reading
                else:
                    yield offset, len(original), token["hira"]
        offset += len(original)


def _input_reading(
    initial, ruby_adjust=1, font_size=6.0,
    font_name="Noto Sans CJK JP", gap=0, base_text=""
):
    """Show a small editor that does not depend on Asian-language UI options."""
    context = uno.getComponentContext()
    service = context.ServiceManager
    model = service.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", context
    )
    model.PositionX = 100
    model.PositionY = 80
    model.Width = 220
    model.Height = 158
    model.Title = "Edit Furigana"

    label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    label.PositionX, label.PositionY = 8, 8
    label.Width, label.Height = 204, 12
    label.Label = "Base: {}    Ruby (separate with |):".format(base_text)
    model.insertByName("label", label)

    field = model.createInstance("com.sun.star.awt.UnoControlEditModel")
    field.PositionX, field.PositionY = 8, 23
    field.Width, field.Height = 204, 15
    field.Text = initial or ""
    field.TabIndex = 0
    model.insertByName("reading", field)

    align_label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    align_label.PositionX, align_label.PositionY = 8, 46
    align_label.Width, align_label.Height = 62, 12
    align_label.Label = "Alignment:"
    model.insertByName("align_label", align_label)

    alignment = model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
    alignment.PositionX, alignment.PositionY = 70, 43
    alignment.Width, alignment.Height = 62, 16
    alignment.StringItemList = ("Left", "Center", "Right")
    alignment.SelectedItems = (ruby_adjust if ruby_adjust in (0, 1, 2) else 1,)
    alignment.Dropdown = True
    alignment.TabIndex = 1
    model.insertByName("alignment", alignment)

    size_label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    size_label.PositionX, size_label.PositionY = 140, 46
    size_label.Width, size_label.Height = 38, 12
    size_label.Label = "Size:"
    model.insertByName("size_label", size_label)

    size = model.createInstance("com.sun.star.awt.UnoControlNumericFieldModel")
    size.PositionX, size.PositionY = 176, 43
    size.Width, size.Height = 36, 16
    size.Value = float(font_size if font_size is not None else 6.0)
    size.ValueMin = 4.0
    size.ValueMax = 30.0
    size.ValueStep = 0.5
    size.DecimalAccuracy = 1
    size.Spin = True
    size.TabIndex = 2
    model.insertByName("size", size)

    font_label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    font_label.PositionX, font_label.PositionY = 8, 72
    font_label.Width, font_label.Height = 42, 12
    font_label.Label = "Font:"
    model.insertByName("font_label", font_label)

    font = model.createInstance("com.sun.star.awt.UnoControlEditModel")
    font.PositionX, font.PositionY = 50, 69
    font.Width, font.Height = 162, 15
    font.Text = font_name or "Noto Sans CJK JP"
    font.TabIndex = 3
    model.insertByName("font", font)

    gap_label = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    gap_label.PositionX, gap_label.PositionY = 8, 96
    gap_label.Width, gap_label.Height = 92, 12
    gap_label.Label = "Gap (%):"
    model.insertByName("gap_label", gap_label)

    gap_field = model.createInstance("com.sun.star.awt.UnoControlNumericFieldModel")
    gap_field.PositionX, gap_field.PositionY = 100, 93
    gap_field.Width, gap_field.Height = 45, 16
    gap_field.Value = float(gap if gap is not None else 0)
    gap_field.ValueMin = -50.0
    gap_field.ValueMax = 100.0
    gap_field.ValueStep = 5.0
    gap_field.DecimalAccuracy = 0
    gap_field.Spin = True
    gap_field.TabIndex = 4
    model.insertByName("gap", gap_field)

    ok = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok.PositionX, ok.PositionY = 80, 122
    ok.Width, ok.Height = 60, 16
    ok.Label = "Apply"
    ok.PushButtonType = 1
    ok.DefaultButton = True
    ok.TabIndex = 5
    model.insertByName("ok", ok)

    cancel = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel.PositionX, cancel.PositionY = 148, 122
    cancel.Width, cancel.Height = 64, 16
    cancel.Label = "Cancel"
    cancel.PushButtonType = 2
    cancel.TabIndex = 6
    model.insertByName("cancel", cancel)

    dialog = service.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", context)
    dialog.setModel(model)
    toolkit = service.createInstanceWithContext("com.sun.star.awt.Toolkit", context)
    desktop = service.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    parent = desktop.getCurrentFrame().getContainerWindow()
    dialog.createPeer(toolkit, parent)
    dialog.getControl("reading").setFocus()
    result = dialog.execute()
    if result == 1:
        value = (
            dialog.getControl("reading").getText(),
            dialog.getControl("alignment").getSelectedItemPos(),
            dialog.getControl("size").getValue(),
            dialog.getControl("font").getText(),
            int(dialog.getControl("gap").getValue()),
        )
    else:
        value = None
    dialog.dispose()
    return value


def _phonetic_guide_dialog(
    rows, ruby_adjust=1, font_size=6.0,
    font_name="Noto Sans CJK JP", gap=0
):
    """Show an Asian Phonetic Guide-like editor with one ruby field per base."""
    context = uno.getComponentContext()
    service = context.ServiceManager
    page_size = 10
    visible_rows = page_size
    row_height = 19
    controls_y = 34 + visible_rows * row_height
    model = service.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", context
    )
    model.PositionX, model.PositionY = 65, 35
    model.Width = 430
    model.Height = controls_y + 132
    model.Title = "Auto Furigana - Phonetic Guide"

    def fixed(name, x, y, width, label):
        item = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
        item.PositionX, item.PositionY = x, y
        item.Width, item.Height = width, 12
        item.Label = label
        model.insertByName(name, item)

    fixed("base_header", 8, 8, 170, "Base text")
    fixed("ruby_header", 188, 8, 170, "Ruby text")

    for index in range(visible_rows):
        base, reading = rows[index] if index < len(rows) else ("", "")
        y = 23 + index * row_height
        base_field = model.createInstance("com.sun.star.awt.UnoControlEditModel")
        base_field.PositionX, base_field.PositionY = 8, y
        base_field.Width, base_field.Height = 170, 15
        base_field.Text = base
        base_field.ReadOnly = True
        model.insertByName("base_{}".format(index), base_field)

        ruby_field = model.createInstance("com.sun.star.awt.UnoControlEditModel")
        ruby_field.PositionX, ruby_field.PositionY = 188, y
        ruby_field.Width, ruby_field.Height = 170, 15
        ruby_field.Text = reading
        ruby_field.TabIndex = index
        model.insertByName("ruby_{}".format(index), ruby_field)

    fixed("mode", 378, 8, 42, "Mono")
    previous = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    previous.PositionX, previous.PositionY = 366, 23
    previous.Width, previous.Height = 20, 15
    previous.Label = "‹"
    model.insertByName("previous", previous)
    fixed("page", 388, 25, 20, "1/1")
    next_button = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    next_button.PositionX, next_button.PositionY = 410, 23
    next_button.Width, next_button.Height = 20, 15
    next_button.Label = "›"
    model.insertByName("next", next_button)
    fixed("align_label", 8, controls_y + 3, 55, "Alignment:")
    alignment = model.createInstance("com.sun.star.awt.UnoControlListBoxModel")
    alignment.PositionX, alignment.PositionY = 63, controls_y
    alignment.Width, alignment.Height = 58, 16
    alignment.StringItemList = ("Left", "Center", "Right")
    alignment.SelectedItems = (ruby_adjust if ruby_adjust in (0, 1, 2) else 1,)
    alignment.Dropdown = True
    model.insertByName("alignment", alignment)

    fixed("position_label", 130, controls_y + 3, 48, "Position:")
    fixed("position", 178, controls_y + 3, 32, "Top")
    fixed("size_label", 320, controls_y + 3, 28, "Size:")
    size = model.createInstance("com.sun.star.awt.UnoControlNumericFieldModel")
    size.PositionX, size.PositionY = 350, controls_y
    size.Width, size.Height = 38, 16
    size.Value = float(font_size if font_size is not None else 6.0)
    size.ValueMin, size.ValueMax, size.ValueStep = 4.0, 30.0, 0.5
    size.DecimalAccuracy, size.Spin = 1, True
    model.insertByName("size", size)

    fixed("font_label", 8, controls_y + 27, 32, "Font:")
    font = model.createInstance("com.sun.star.awt.UnoControlEditModel")
    font.PositionX, font.PositionY = 40, controls_y + 24
    font.Width, font.Height = 205, 15
    font.Text = font_name or "Noto Sans CJK JP"
    model.insertByName("font", font)

    fixed("gap_label", 265, controls_y + 27, 48, "Gap (%):")
    gap_field = model.createInstance("com.sun.star.awt.UnoControlNumericFieldModel")
    gap_field.PositionX, gap_field.PositionY = 315, controls_y + 24
    gap_field.Width, gap_field.Height = 58, 16
    gap_field.Value = float(gap if gap is not None else 0)
    gap_field.ValueMin, gap_field.ValueMax, gap_field.ValueStep = -50.0, 100.0, 5.0
    gap_field.DecimalAccuracy, gap_field.Spin = 0, True
    model.insertByName("gap", gap_field)

    fixed("preview_label", 8, controls_y + 50, 45, "Preview:")
    preview_frame = model.createInstance("com.sun.star.awt.UnoControlGroupBoxModel")
    preview_frame.PositionX, preview_frame.PositionY = 55, controls_y + 43
    preview_frame.Width, preview_frame.Height = 365, 57
    preview_frame.Label = ""
    model.insertByName("preview_frame", preview_frame)
    preview_rows = rows[:page_size]
    ruby_preview = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    ruby_preview.PositionX, ruby_preview.PositionY = 63, controls_y + 51
    ruby_preview.Width, ruby_preview.Height = 349, 16
    ruby_preview.Label = "　".join(reading for _base, reading in preview_rows)
    ruby_preview.Align = 1
    ruby_font = uno.createUnoStruct("com.sun.star.awt.FontDescriptor")
    ruby_font.Height = 11
    ruby_preview.FontDescriptor = ruby_font
    model.insertByName("ruby_preview", ruby_preview)
    base_preview = model.createInstance("com.sun.star.awt.UnoControlFixedTextModel")
    base_preview.PositionX, base_preview.PositionY = 63, controls_y + 70
    base_preview.Width, base_preview.Height = 349, 22
    base_preview.Label = "　".join(base for base, _reading in preview_rows)
    base_preview.Align = 1
    base_font = uno.createUnoStruct("com.sun.star.awt.FontDescriptor")
    base_font.Height = 18
    base_preview.FontDescriptor = base_font
    model.insertByName("base_preview", base_preview)

    ok = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    ok.PositionX, ok.PositionY = 296, controls_y + 107
    ok.Width, ok.Height = 58, 17
    ok.Label, ok.PushButtonType, ok.DefaultButton = "Apply", 1, True
    model.insertByName("ok", ok)
    cancel = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    cancel.PositionX, cancel.PositionY = 362, controls_y + 107
    cancel.Width, cancel.Height = 58, 17
    cancel.Label, cancel.PushButtonType = "Cancel", 2
    model.insertByName("cancel", cancel)

    dialog = service.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", context)
    dialog.setModel(model)
    toolkit = service.createInstanceWithContext("com.sun.star.awt.Toolkit", context)
    desktop = service.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    dialog.createPeer(toolkit, desktop.getCurrentFrame().getContainerWindow())
    editable_rows = [[base, reading] for base, reading in rows]
    pager = _GuidePager(dialog, editable_rows, page_size)
    dialog.getControl("previous").setActionCommand("previous")
    dialog.getControl("next").setActionCommand("next")
    dialog.getControl("previous").addActionListener(pager)
    dialog.getControl("next").addActionListener(pager)
    pager.show()
    dialog.getControl("ruby_0").setFocus()
    result = dialog.execute()
    if result == 1:
        pager._save()
        value = (
            [reading for _base, reading in editable_rows],
            dialog.getControl("alignment").getSelectedItemPos(),
            dialog.getControl("size").getValue(),
            dialog.getControl("font").getText(),
            int(dialog.getControl("gap").getValue()),
        )
    else:
        value = None
    dialog.dispose()
    return value


def _ruby_style(document, font_size, font_name="Noto Sans CJK JP", gap=0):
    """Get or create a character style used only by ruby annotations."""
    size = max(4.0, min(30.0, round(float(font_size or 6.0) * 2) / 2))
    font_name = (font_name or "Noto Sans CJK JP").strip()
    gap = max(-50, min(100, int(gap)))
    signature = "{}|{}|{}".format(size, font_name, gap).encode("utf-8")
    suffix = hashlib.sha1(signature).hexdigest()[:8]
    name = "AutoFurigana Ruby {}pt {}".format(str(size).replace(".0", ""), suffix)
    styles = document.getStyleFamilies().getByName("CharacterStyles")
    if not styles.hasByName(name):
        style = document.createInstance("com.sun.star.style.CharacterStyle")
        style.setPropertyValue("CharHeight", size)
        style.setPropertyValue("CharHeightAsian", size)
        style.setPropertyValue("CharFontName", font_name)
        style.setPropertyValue("CharFontNameAsian", font_name)
        style.setPropertyValue("CharEscapement", gap)
        style.setPropertyValue("CharEscapementHeight", 100)
        # Never add a printed background/highlight to generated ruby text.
        for prop, value in (
            ("CharBackColor", -1),
            ("CharBackTransparent", True),
            ("CharHighlight", -1),
        ):
            try:
                style.setPropertyValue(prop, value)
            except Exception:
                pass
        styles.insertByName(name, style)
    return name


def _ruby_size(document, style_name):
    if not style_name:
        return 6.0
    try:
        style = document.getStyleFamilies().getByName("CharacterStyles").getByName(style_name)
        return float(style.getPropertyValue("CharHeightAsian") or 6.0)
    except Exception:
        return 6.0


def _ruby_style_values(document, style_name):
    if not style_name:
        return "Noto Sans CJK JP", 0
    try:
        style = document.getStyleFamilies().getByName("CharacterStyles").getByName(style_name)
        font = style.getPropertyValue("CharFontNameAsian") or "Noto Sans CJK JP"
        gap = int(style.getPropertyValue("CharEscapement") or 0)
        return font, gap
    except Exception:
        return "Noto Sans CJK JP", 0


def apply_furigana(*_args):
    context = uno.getComponentContext()
    desktop = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context
    )
    document = desktop.getCurrentComponent()
    if document is None or not document.supportsService("com.sun.star.text.TextDocument"):
        _message("Please open a Writer document.", error=True)
        return

    selection = _selection(document)
    text = selection.getString() if selection else ""
    if not text:
        _message("Select Japanese text first.")
        return

    annotations = list(_segments(text))
    if not annotations:
        _message("The selection does not contain Kanji.")
        return

    document.lockControllers()
    try:
        source = selection.getStart()
        ruby_style = _ruby_style(document, 6.0, "Noto Sans CJK JP", 0)
        for offset, length, reading in annotations:
            cursor = selection.getText().createTextCursorByRange(source)
            cursor.goRight(offset, False)
            cursor.goRight(length, True)
            cursor.setPropertyValue("RubyText", reading)
            cursor.setPropertyValue("RubyIsAbove", True)
            cursor.setPropertyValue("RubyAdjust", 1)
            cursor.setPropertyValue("RubyCharStyleName", ruby_style)
    finally:
        document.unlockControllers()


def _selection_has_ruby(selection, text):
    """Check generated ranges so reopening the guide never overwrites corrections."""
    source = selection.getStart()
    try:
        for offset, length, _reading in _segments(text):
            cursor = selection.getText().createTextCursorByRange(source)
            cursor.goRight(offset, False)
            cursor.goRight(length, True)
            if cursor.getPropertyValue("RubyText"):
                return True
    except Exception:
        # An ambiguous property normally means multiple ruby values are present.
        return True
    return False


def phonetic_guide(*_args):
    """Auto-fill ruby when needed, then open the extension's reliable editor."""
    context = uno.getComponentContext()
    desktop = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context
    )
    document = desktop.getCurrentComponent()
    if document is None or not document.supportsService("com.sun.star.text.TextDocument"):
        _message("Please open a Writer document.", error=True)
        return

    selection = _selection(document)
    text = selection.getString() if selection else ""
    if not text:
        _message("Select Japanese text first.")
        return
    if not _selection_has_ruby(selection, text):
        apply_furigana()
    edit_furigana()


def edit_furigana(*_args):
    context = uno.getComponentContext()
    desktop = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context
    )
    document = desktop.getCurrentComponent()
    if document is None or not document.supportsService("com.sun.star.text.TextDocument"):
        _message("Please open a Writer document.", error=True)
        return

    selection = _selection(document)
    if selection is None or not selection.getString():
        _message("Double-click or select one Japanese word first.")
        return
    text = selection.getString()
    source = selection.getStart()
    ranges = []
    for offset, length, automatic in _segments(text):
        cursor = selection.getText().createTextCursorByRange(source)
        cursor.goRight(offset, False)
        cursor.goRight(length, True)
        try:
            current = cursor.getPropertyValue("RubyText") or automatic
            ruby_adjust = int(cursor.getPropertyValue("RubyAdjust"))
            style_name = cursor.getPropertyValue("RubyCharStyleName") or ""
        except Exception:
            current, ruby_adjust, style_name = automatic, 1, ""
        ranges.append((cursor, cursor.getString(), current))
    if not ranges:
        _message("The selection does not contain Kanji.")
        return

    font_name, gap = _ruby_style_values(document, style_name)
    edited = _phonetic_guide_dialog(
        [(base, reading) for _cursor, base, reading in ranges],
        ruby_adjust, _ruby_size(document, style_name), font_name, gap
    )
    if edited is not None:
        readings, ruby_adjust, font_size, font_name, gap = edited
        style = _ruby_style(document, font_size, font_name, gap)
        for (cursor, _base, _old), reading in zip(ranges, readings):
            cursor.setPropertyValue("RubyText", reading)
            cursor.setPropertyValue("RubyIsAbove", True)
            cursor.setPropertyValue("RubyAdjust", ruby_adjust)
            cursor.setPropertyValue("RubyCharStyleName", style)
        # Remove the selection highlight after Apply.
        try:
            document.getCurrentController().getViewCursor().gotoRange(
                selection.getEnd(), False
            )
        except Exception:
            pass
        _hide_field_shading(document)


g_exportedScripts = (phonetic_guide, apply_furigana, edit_furigana)
