# 階段實作報告

本目錄存放各開發階段的**實作報告**，記錄設計決策、實作細節與遭遇的技術挑戰。
與 `docs/` 的區別：`docs/` 是「如何做」的實作指南，本目錄是「做了什麼、為什麼這樣做」的記錄。

---

## 命名規範

| 檔名 | 對應階段 |
|---|---|
| `stage0-schema-design.md` | Schema 設計決策（關聯式 + 圖形） |
| `stage1-a-relational-queries.md` | 主軸 A：PostgreSQL 查詢函式（docs 04–12） |
| `stage1-b-graph-queries.md` | 主軸 B：Neo4j 圖形查詢（docs 13–20） |
| `stage2-advanced-features.md` | 進階功能（docs 21–22，選做） |
| `stage3-infrastructure.md` | Stage 3 基礎設施（docs 23–26） |

---

## 每份報告建議包含

1. **實作範圍**：涵蓋哪些函式 / 模組
2. **設計決策**：採用什麼方案、比較了哪些選項、最終理由
3. **關鍵 SQL / Cypher**：非顯而易見的查詢邏輯說明
4. **已知限制**：目前版本的邊界條件或已知 bug
5. **測試結果摘要**：哪些測試通過、哪些跳過、遺留問題
