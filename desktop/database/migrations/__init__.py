"""資料庫遷移腳本目錄。

命名慣例：
    v{version}_{description}.py   例如 v2_add_tags_column.py

Round 2：保留空目錄，供未來版本 schema 遷移使用。
Round 3+：HistoryDB 初始化時按版本號依序執行遷移腳本。
"""
