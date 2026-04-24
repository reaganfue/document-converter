# 測試 Markdown 文件

## 第一節 — 段落

這是一段普通段落，包含中英文混合文字。
This is a mixed Chinese-English paragraph for testing.

## 第二節 — 強調語法

**粗體文字** 和 *斜體文字* 的測試。
***粗斜體*** 也應該被正確處理。

## 第三節 — 清單

### 無序清單

- 第一個項目
- 第二個項目
  - 子項目 A
  - 子項目 B
- 第三個項目

### 有序清單

1. 步驟一
2. 步驟二
3. 步驟三

## 第四節 — 連結與代碼

這是一個 [超連結](https://example.com)。

行內代碼：`print("Hello")`

代碼塊：

```python
def convert_file(src, dst):
    print(f"Converting {src} to {dst}")
    return True
```

## 第五節 — 表格

| 格式 | 來源 | 目標 | 保真度 |
|------|------|------|--------|
| PDF  | ✓    | ✓    | 高     |
| DOCX | ✓    | ✓    | 高     |
| HTML | ✓    | ✓    | 高     |

## 第六節 — 引用

> 這是一段引用文字。
> 可以跨多行。

---

文件結束。
