# TransitFlow — 智慧鐵路助理

> **IM2002 資料庫管理 — 期末專案**
> 組別：9（3 人；分工見 Work Allocation Report，經 EEClass 繳交）
> 評分標準：https://github.com/NCUIM-Lab710-Teaching/IM2002-grading-students

TransitFlow 是一個雙網路（城市捷運 + 國鐵）交通營運商的 AI 聊天助理。它透過查詢
**三種資料庫**並由 LLM 組裝回覆來回答問題：

| 資料庫 | 用途 |
|---|---|
| **PostgreSQL** | 結構化資料 — 站點、班次、座位、使用者、訂票、付款 |
| **PostgreSQL + pgvector** | 政策文件，依「語意」檢索（RAG） |
| **Neo4j** | 鐵路網路圖 — 路線規劃、轉乘、延誤擴散 |

代理層（`skeleton/agent.py`）透過 LLM 工具呼叫，把每個問題路由到正確的資料庫，
再組裝答案。資料庫設計與 LLM/RAG 背景請見
[docs/transitflow-db-tutorial.md](docs/transitflow-db-tutorial.md) 與
[docs/transitflow-llm-tutorial.md](docs/transitflow-llm-tutorial.md)。

---

## 快速開始

前置需求：**Docker Desktop**、**Python 3.10+**，以及一個 LLM —— **Ollama**
（預設、本機、免金鑰）或 Gemini（設定 `LLM_PROVIDER=gemini` + `GEMINI_API_KEY`）。
下方指令為 Windows 的 `python`；macOS/Linux 請用 `python3`。

```powershell
# 1. 建立虛擬環境並安裝依賴
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. 建立環境設定檔（預設 Ollama；PostgreSQL 對外為 5433 埠）
copy .env.example .env

# 3.（僅 Ollama）拉取聊天 + 嵌入模型，一次即可
ollama pull llama3.2:1b
ollama pull nomic-embed-text

# 4. 啟動資料庫（PostgreSQL 5433、Neo4j 7688/7475、pgAdmin 5051）
docker compose up -d
docker compose ps        # 等兩個 DB 容器顯示 "healthy"

# 5. Seed 三個資料庫（冪等，可安全重跑）
python skeleton/seed_postgres.py     # 關聯式表格（密碼以 argon2 雜湊）
python skeleton/seed_neo4j.py        # 圖形：MetroStation/NationalRailStation 節點 + METRO_LINK / RAIL_LINK / INTERCHANGE_TO
python skeleton/seed_vectors.py      # pgvector 政策文件嵌入

# 6. 啟動助理
python skeleton/ui.py                # 開啟 http://localhost:7860
```

> 變更 `databases/relational/schema.sql` 後，需重建 volume：
> `docker compose down -v && docker compose up -d`，再重新 seed 三個資料庫。

---

## 執行測試

```powershell
pytest tests/unit/          # 快速，免資料庫（皆 mock）
pytest tests/integration/   # 需 Docker 已啟動 + 三個 DB 已 seed
pytest                      # 全部
```

`pytest.ini` 設定 `--import-mode=importlib`。目前套件共 **415 個測試通過**
（單元 347 + 整合 68）。少數測試刻意保留但在收集階段跳過（見 `tests/conftest.py`），
因為它們依賴非本次繳交範圍的選做模組。

---

## 批改導覽（grading map）

本專案分三個組件評分；以下對應到 repo 中的位置：

| 組件（／100） | 在本 repo 的佐證位置 |
|---|---|
| **靜態程式碼** | `databases/relational/schema.sql`（schema）、`databases/relational/queries.py`（PostgreSQL 查詢）、`skeleton/seed_postgres.py`（種子）、`databases/graph/seed.cypher` + `skeleton/seed_neo4j.py`（圖形設計 + 種子）、`databases/graph/queries.py`（Cypher 查詢） |
| **設計文件** | `Team09_DESIGN_DOC.md`（ER、正規化、圖形理由、RAG、AI 使用、反思）。背景素材：`docs/` 下的兩份 tutorial |
| **現場測試** | 依上方「快速開始」執行 —— 助教會 seed 資料庫並操作 Gradio UI |

團隊流程與貢獻紀錄：[TEAM.md](TEAM.md)（工作分配、Git 流程）、
[AI_SESSION_CONTEXT.md](AI_SESSION_CONTEXT.md)（固定函式契約）、
以及 `reports/` 下的實作／測試報告。

---

## 架構說明

- **`databases/`** 是工作區，依資料庫類型分組（`relational/`、`graph/`、`vector/`）。
- **`skeleton/`** 是管線：`agent.py`（依賴注入的 `TransitFlowAgent`、工具路由、
  結構化日誌 + Prometheus 指標）、`database_service.py`（資料庫存取介面）、
  `cache.py`（票價／班次的 LRU+TTL 快取）、`health_check.py`（`healthz()`）、
  `config.py` / `llm_provider.py`（請勿修改），以及三個 `seed_*` 腳本。
- 座位可用性與訂票**絕不快取**（避免超賣）；只有票價與捷運班次會快取。

## 參考資料

課程提供的素材保存於 `docs/`：

- [docs/README-teacher-updated.md](docs/README-teacher-updated.md) —— 老師最新版專案 README
- [docs/README-original.md](docs/README-original.md) —— 原始起始 README
- [docs/transitflow-db-tutorial.md](docs/transitflow-db-tutorial.md) —— 資料庫設計
- [docs/transitflow-llm-tutorial.md](docs/transitflow-llm-tutorial.md) —— LLM、嵌入、RAG

## 疑難排解

- **安裝出現 websockets 依賴衝突** —— 請在**乾淨的虛擬環境**安裝。`requirements.txt`
  使用 **Gradio 6**：Gradio 4.x 會與 `google-genai`（`skeleton/llm_provider.py` 一律
  import 的套件）在 `websockets` 版本上衝突，故必須用 Gradio 6。`ui.py` 將 `theme`
  傳給 `.launch()`（Gradio 6 的寫法）。
- **`embedding dimension mismatch`** —— seed 之後換了嵌入模型。請固定單一
  `LLM_PROVIDER`；`schema.sql` 對 Ollama 用 `vector(768)`（Gemini 用 `vector(3072)`），
  然後重建 volume 並重新 seed。
- **Neo4j 連線錯誤** —— Neo4j 約需 30 秒才會 healthy；稍候再重跑 seed。
