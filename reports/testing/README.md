# 測試報告

本目錄存放單元測試與整合測試的**執行報告**，作為驗收依據與進度紀錄。

---

## 命名規範

| 檔名 | 說明 |
|---|---|
| `unit-test-report.md` | 單元測試結果與函式覆蓋狀況 |
| `integration-test-report.md` | 整合測試結果（需 Docker 環境運行） |
| `final-validation-report.md` | 最終驗收報告（`pytest tests/ -v` 全部 PASS） |

---

## 標準測試執行指令

```bash
# 環境確認
docker compose ps   # 確認 postgres / neo4j / pgadmin 均為 Up

# 單元測試（不需 DB 連線）
pytest tests/unit/ -v --tb=short

# 整合測試（需 DB 連線）
pytest tests/integration/ -v --tb=short

# 特定函式測試
pytest tests/unit/ -v -k "national_rail_fare or metro_schedules"
pytest tests/unit/ -v -k "metro_fare or available_seats"
pytest tests/unit/ -v -k "solid_refactor"
pytest tests/unit/ -v -k "performance_boost"

# 完整驗收
pytest tests/ -v --tb=short
```

---

## 報告格式建議

每份測試報告應包含：
- 執行日期與環境（Python 版本、Docker 映像版本）
- 測試指令與輸出摘要（通過 / 失敗 / 跳過數量）
- 失敗項目說明與處理方式
- 覆蓋率數據（若有）
