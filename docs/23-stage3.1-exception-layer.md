# 23 — Stage 3.1｜全局異常處理層（Exception Layer）

> **前置條件**：`skeleton/agent.py` 存在（可 import）
> **後續任務**：`24-stage3.2-solid-refactor.md`

---

## 任務目標

在 `skeleton/exceptions.py` 中定義完整的異常類別層次，並在 `skeleton/agent.py` 中
實作 `error_handler` 裝飾器，確保所有工具呼叫的例外都被轉換為結構化 JSON 回應，
前端永遠不會收到 Python traceback。

**目標檔案**：
- `skeleton/exceptions.py`（定義異常類別）
- `skeleton/agent.py`（新增 `error_handler` 裝飾器 + 套用到 `_execute_tool`）

---

## 介面規格

### skeleton/exceptions.py

```python
class TransitFlowException(Exception):
    def __init__(self, message: str, error_code: str = ""):
        super().__init__(message)
        self.message = message
        self.error_code = error_code

class DatabaseException(TransitFlowException): ...
class ValidationException(TransitFlowException): ...
class RouteNotFoundException(TransitFlowException): ...
class SeatUnavailableException(TransitFlowException): ...
```

**繼承關係**：四個子類別全部繼承自 `TransitFlowException`，不額外覆寫任何方法。

### skeleton/agent.py — error_handler 裝飾器

```python
import functools, json

def error_handler(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except TransitFlowException as e:
            return json.dumps({
                "success": False,
                "error": {"message": e.message, "code": e.error_code}
            })
        except Exception:
            return json.dumps({
                "success": False,
                "error": {"code": "INTERNAL_ERROR"}
            })
    return wrapper
```

**套用位置**：`_execute_tool` 方法必須加上 `@error_handler`。

---

## 實作要點

### TransitFlowException 規格

| 屬性 | 說明 |
|---|---|
| `.message` | 建構子第一個參數，也透過 `super().__init__(message)` 傳入 |
| `.error_code` | 建構子第二個參數，預設值為空字串 `""` |

**重要**：`str(exception)` 必須包含 `.message` 的內容（由 `super().__init__(message)` 保證）。

### error_handler 規格

| 情境 | 行為 |
|---|---|
| 函式正常回傳 | 原樣回傳，不做任何修改 |
| 拋出 `TransitFlowException`（含子類別） | 回傳 `json.dumps({"success": False, "error": {"message": e.message, "code": e.error_code}})` |
| 拋出任何其他 `Exception` | 回傳 `json.dumps({"success": False, "error": {"code": "INTERNAL_ERROR"}})` |

**`functools.wraps` 的要求**：
- 裝飾後函式的 `.__name__` 必須等於原始函式名稱
- 裝飾後函式的 `.__doc__` 必須等於原始函式 docstring
- 必須有 `.__wrapped__` 屬性指向原始函式（`functools.wraps` 自動設定）

**不能出現在輸出中**：
- `"Traceback"`
- `"File "`
- `"line "`

---

## 驗收標準

**測試驗證的關鍵行為**：

`TransitFlowException`：
1. `.message` 和 `.error_code` 屬性正確儲存
2. 預設 `error_code` 為空字串
3. 是 `Exception` 的子類別
4. `str(e)` 包含 `.message`

四個子類別（`DatabaseException`、`ValidationException`、`RouteNotFoundException`、`SeatUnavailableException`）：
1. 全部繼承自 `TransitFlowException`
2. 可用 `except TransitFlowException` 捕捉
3. `.message` 和 `.error_code` 正確繼承

`error_handler`：
1. 正常回傳值原樣通過
2. `TransitFlowException` 子類別 → `{"success": false, "error": {"message": ..., "code": ...}}`
3. 未知 `Exception` → `{"success": false, "error": {"code": "INTERNAL_ERROR"}}`
4. 輸出為合法 JSON 字串，不含 traceback 文字
5. 透過 `functools.wraps` 保留函式名稱、docstring、`__wrapped__`

`_execute_tool` 整合（⚠️ 此子項需 **Stage 3.2 完成後** 才能通過）：

> `TransitFlowAgent` 類別與 `_default_agent` 實例均在 Stage 3.2 定義（見 `24-stage3.2-solid-refactor.md`）。
> Stage 3.1 完成後，先以 `-k "exception_layer"` 確認上方 `TransitFlowException` 和 `error_handler` 基本行為通過；
> `_execute_tool` 整合項目在 Stage 3.2 的 `solid_refactor` 測試中也會一併驗收，在此之前失敗屬預期。

1. `_execute_tool.__wrapped__` 屬性存在（確認裝飾器已套用）
2. 服務方法拋出 `RouteNotFoundException` → 回傳結構化 JSON，不崩潰
3. 服務方法拋出 `DatabaseException` → 結構化 JSON
4. 服務方法拋出 `RuntimeError` → `INTERNAL_ERROR` 代碼

**執行測試**：
```bash
pytest tests/unit/ -v -k "exception_layer"
```

---

## 注意事項

- `error_handler` 裝飾器定義在 `skeleton/agent.py` 中，並從該模組匯出（`from skeleton.agent import error_handler`）
- 測試會直接 `from skeleton.exceptions import TransitFlowException, DatabaseException, ...` 匯入
- 測試也會 `from skeleton.agent import _default_agent, error_handler` 匯入
- `_default_agent` 是 `skeleton/agent.py` 模組層級的預設代理實例（Stage 3.2 實作）
