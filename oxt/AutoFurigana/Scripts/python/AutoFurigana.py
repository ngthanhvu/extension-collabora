"""Offline Auto Furigana macro for Collabora Office Writer."""

from pathlib import Path
import hashlib
import re
import sys

import uno


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


def _segments(text):
    """Return (offset, length, reading) for tokens containing kanji."""
    offset = 0
    for token in _converter().convert(text):
        original = token["orig"]
        if KANJI.search(original):
            yield offset, len(original), token["hira"]
        offset += len(original)


def _input_reading(
    initial, ruby_adjust=1, font_size=6.0,
    font_name="Noto Sans CJK JP", gap=0
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
    label.Label = "Hiragana reading:"
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
    try:
        current = selection.getPropertyValue("RubyText") or ""
    except Exception:
        current = ""
    try:
        ruby_adjust = int(selection.getPropertyValue("RubyAdjust"))
        style_name = selection.getPropertyValue("RubyCharStyleName") or ""
    except Exception:
        ruby_adjust, style_name = 1, ""
    font_name, gap = _ruby_style_values(document, style_name)
    edited = _input_reading(
        current, ruby_adjust, _ruby_size(document, style_name), font_name, gap
    )
    if edited is not None:
        reading, ruby_adjust, font_size, font_name, gap = edited
        selection.setPropertyValue("RubyText", reading.strip())
        selection.setPropertyValue("RubyIsAbove", True)
        selection.setPropertyValue("RubyAdjust", ruby_adjust)
        selection.setPropertyValue(
            "RubyCharStyleName", _ruby_style(document, font_size, font_name, gap)
        )


g_exportedScripts = (apply_furigana, edit_furigana)
