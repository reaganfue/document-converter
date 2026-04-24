# static/ 目錄說明

此目錄為**已廢止的 Web 版資源**，桌面應用版本（v2.0+）已不使用此目錄。

## 內容清單

| 路徑 | 說明 | 狀態 |
|------|------|------|
| `css/design-tokens.css` | CSS 設計代幣（CSS 變數，暗色主題） | 廢止 |
| `css/app.css` | Web 版全域樣式 | 廢止 |
| `css/vendor/tailwind.min.css` | Tailwind CSS 本地快取 | 廢止 |
| `js/app.js` | Web 版主邏輯（XHR 上傳、輪詢、下載觸發） | 廢止 |
| `js/uploader.js` | Web 版上傳邏輯 | 廢止 |
| `js/vendor/alpine.min.js` | Alpine.js 本地快取 | 廢止 |
| `icons/*.svg` | 格式圖示（PDF / DOCX / PPTX / HTML / MD / TXT / Image） | 已複製至桌面版 |
| `favicon.ico` | 網站圖示 | 廢止 |

## 遷移說明

- SVG 格式圖示已複製到 `desktop/resources/icons/`，桌面版從此處載入
- Tailwind CSS / Alpine.js 為 Web 版前端框架，桌面版改用 PySide6 + QFluentWidgets
- 設計代幣（CSS 變數）不適用於 Qt 應用，桌面版色彩由 `desktop/utils/theme.py` 管理

## 是否可刪除？

保留此目錄以利未來需要恢復 Web 版時可快速還原。

若確認永不需要 Web 版，可安全刪除整個 `static/` 目錄。
