# Auto Furigana cho Collabora Office

Extension offline dành cho **Collabora Office 25.04 trên Zorin OS/Linux**. Giáo
viên chọn văn bản tiếng Nhật trong Writer và bấm **Auto Furigana** để thêm cách
đọc hiragana tương tự Asian Phonetic Guide.

## Cài đặt cho giáo viên

File cài đặt phiên bản 0.7.1 đã được tạo tại
[`dist/AutoFurigana-0.7.1.oxt`](dist/AutoFurigana-0.7.1.oxt).

1. Nếu đã cài bản cũ, mở **Tools > Extension Manager**, chọn Auto Furigana và
   bấm **Remove**.
2. Đóng hoàn toàn tất cả cửa sổ Collabora Office.
3. Mở lại Collabora Office, nhấp đúp vào `AutoFurigana-0.7.1.oxt`.
4. Chọn **Install** trong Extension Manager.
5. Đóng và mở lại Collabora Office Writer.

Nếu nhấp đúp không mở Extension Manager:

1. Mở Collabora Office Writer.
2. Chọn **Tools > Extension Manager > Add**.
3. Chọn file `AutoFurigana.oxt` và xác nhận cài đặt.

## Sử dụng

1. Bôi đen một câu hoặc đoạn tiếng Nhật có Kanji.
2. Chọn **Tools > Add-ons > Auto Furigana** hoặc nút **Auto Furigana** trên
   toolbar của add-on.
3. Furigana được thêm trực tiếp vào tài liệu.

### Sửa cách đọc sai

1. Bôi đen từ có furigana không đúng.
2. Chọn **Tools > Add-ons > Edit Furigana** hoặc nút **Edit Furigana**.
3. Nhập lại Hiragana, chọn căn **Left/Center/Right**, chỉnh **Size**, **Font**
   và **Gap**.
4. Bấm **Apply**.

`Gap = 0` là khoảng cách mặc định. Số dương đẩy Hiragana xa Kanji hơn; số âm
đưa Hiragana gần Kanji hơn.

Extension chạy hoàn toàn offline. Máy của giáo viên không cần Node.js, Python,
Docker hoặc API riêng.

## Gỡ cài đặt

Vào **Tools > Extension Manager**, chọn **Auto Furigana**, bấm **Remove** rồi
khởi động lại Collabora Office.

## Dành cho người phát triển

Mã extension nằm trong `oxt/AutoFurigana`. Build lại bằng:

```bash
./scripts/build-oxt.sh
```

Tên kết quả có kèm version, ví dụ `dist/AutoFurigana-0.7.1.oxt`.

Thư viện nhúng:

- PyKakasi 2.3.0 — GPL-3.0-or-later.
- jaconv 0.5.0 — MIT.

## Giới hạn hiện tại

- Chỉ hỗ trợ Writer và vùng chọn văn bản thông thường.
- Cách đọc được suy đoán tự động; tên riêng hoặc Kanji nhiều cách đọc đôi khi
  cần chỉnh lại bằng Asian Phonetic Guide.
- Add-on toolbar có thể nằm trong **View > Toolbars** tùy bố cục giao diện.
