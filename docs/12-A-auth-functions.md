# 12 — 主軸 A｜認證函式（Argon2id 密碼雜湊 + 密碼重設流程）

> **前置條件**：`04-A-schema-core-tables.md`（`users` 表含 `password`、`secret_question`、`secret_answer` 欄位）
> **後續任務**：無（A 主軸最終任務）

---

## 任務目標

在 `databases/relational/queries.py` 中實作五個認證函式：
`register_user`、`login_user`、`get_user_secret_question`、`verify_secret_answer`、`update_password`。

---

## 介面規格

### 函式一：`register_user`

```python
def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
```

**成功回傳**：`(True, "RU021")`（`user_id` 字串）
**失敗回傳**：`(False, "Email 'x@x.com' is already registered")`

**user_id 生成規則**：
1. 查詢目前最大的 `RU` 序號：`MAX(CAST(SUBSTRING(user_id FROM 3) AS INTEGER)) WHERE user_id ~ '^RU[0-9]+$'`
2. 若結果為 NULL（無任何 RU 格式使用者），序號從 1 開始
3. 新 user_id = `f"RU{max_seq + 1:02d}"`（最少兩位數，如 `RU01`、`RU09`、`RU10`）

**密碼雜湊**：使用 `PasswordHasher()` 的 `.hash(password)` 方法（Argon2id 演算法）
**date_of_birth**：存為 `f"{year_of_birth}-01-01"`（年份精度，月日固定為 01-01）
**full_name**：`f"{first_name} {surname}".strip()`

---

### 函式二：`login_user`

```python
def login_user(email: str, password: str) -> Optional[dict]:
```

**成功回傳**：

```json
{
  "user_id": "RU01",
  "email": "alice@example.com",
  "full_name": "Alice Johnson",
  "first_name": "Alice",
  "surname": "Johnson",
  "phone": "+1-555-0101",
  "date_of_birth": "1990-01-01",
  "is_active": true
}
```

**失敗回傳**：`None`（email 不存在、密碼錯誤、或 `is_active=False` 的帳號）

`first_name` 和 `surname` 從 `full_name` 分割（以第一個空格為分隔點）。

---

### 函式三：`get_user_secret_question`

```python
def get_user_secret_question(email: str) -> Optional[str]:
```

回傳密碼重設問題字串。email 不存在時回傳 `None`。

---

### 函式四：`verify_secret_answer`

```python
def verify_secret_answer(email: str, answer: str) -> bool:
```

不分大小寫比對（`row[0].strip().lower() == answer.strip().lower()`）。
email 不存在或 secret_answer 為 NULL 時回傳 `False`。

---

### 函式五：`update_password`

```python
def update_password(email: str, new_password: str) -> bool:
```

回傳 `True` 表示成功更新（`cur.rowcount > 0`），`False` 表示 email 不存在。
密碼同樣使用 Argon2id 雜湊後儲存（`_ph.hash(new_password)`）。

---

## 實作邏輯導引

### register_user 邏輯步驟

```
偽代碼：

conn = None
try:
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. 檢查 email 唯一性
        cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            conn.rollback()
            return (False, f"Email '{email}' is already registered")
        
        # 2. 計算下一個 user_id 序號
        cur.execute(
            "SELECT MAX(CAST(SUBSTRING(user_id FROM 3) AS INTEGER)) AS max_seq "
            "FROM users WHERE user_id ~ '^RU[0-9]+$'"
        )
        row = cur.fetchone()
        max_seq = row["max_seq"] if row and row["max_seq"] is not None else 0
        new_user_id = f"RU{max_seq + 1:02d}"
        
        # 3. 組裝欄位值
        full_name = f"{first_name} {surname}".strip()
        dob = f"{year_of_birth}-01-01"
        hashed_password = _ph.hash(password)   ← Argon2id 雜湊
        
        # 4. 插入
        cur.execute("""
            INSERT INTO users (user_id, full_name, email, password, date_of_birth,
                               secret_question, secret_answer, is_active)
            VALUES (%s, %s, %s, %s, %s::DATE, %s, %s, TRUE)
        """, (new_user_id, full_name, email, hashed_password, dob,
              secret_question, secret_answer))
        
        conn.commit()
    
    return (True, new_user_id)

except psycopg2.errors.UniqueViolation:
    if conn: conn.rollback()
    return (False, f"Email '{email}' is already registered")

except psycopg2.Error as exc:
    if conn: conn.rollback()
    return (False, f"Database error: {exc}")

finally:
    if conn: conn.close()
```

**為何需要捕獲 `UniqueViolation`？**
即使步驟 1 的唯一性檢查已存在，在高並發場景下兩個請求可能同時通過檢查，
PostgreSQL 的唯一約束是最後一道防線，必須捕獲 `psycopg2.errors.UniqueViolation`。

### login_user 邏輯步驟

```
偽代碼：

1. 使用 _connect()（read-only，autocommit=True）：
   SELECT user_id, full_name, email, phone, date_of_birth, is_active, password
   FROM users WHERE email = %s
   
2. row 為 None → 回傳 None（email 不存在）
3. row["is_active"] 為 False → 回傳 None（帳號停用）

4. Argon2id 密碼驗證：
   try:
       _ph.verify(row["password"], password)  ← Argon2id 的時間恆定比對
   except VerifyMismatchError:
       return None  ← 密碼錯誤

5. 分割 full_name：
   parts = row["full_name"].split(" ", 1)
   first_name = parts[0]
   surname = parts[1] if len(parts) > 1 else ""

6. 組裝並回傳 dict（不含 password 欄位）
```

**為何使用 `_ph.verify()` 而非自行計算雜湊比對？**
Argon2id 的雜湊值包含隨機 salt，每次雜湊結果不同，不能直接比較字串。
`verify()` 方法知道如何從雜湊值中提取 salt 並重新計算。

### update_password 邏輯步驟

```
偽代碼：

with _connect() as conn:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET password = %s WHERE email = %s",
            (_ph.hash(new_password), email)
        )
        return cur.rowcount > 0
```

**注意**：`_connect()` 使用 `autocommit=True`，單一 UPDATE 語句自動提交，此處行為正確。

---

## 驗收標準

**驗收測試**：

**測試驗證的關鍵行為**：

`register_user`：
1. 新 email 成功注冊，回傳 `(True, "RU0X")`
2. 重複 email 回傳 `(False, "Email '...' is already registered")`
3. 連續注冊兩個使用者，user_id 序號遞增（RU01 → RU02）

`login_user`：
1. 正確 email + 密碼回傳使用者 dict（含 `first_name`、`surname` 分割結果）
2. 錯誤密碼回傳 `None`
3. 不存在 email 回傳 `None`
4. 停用帳號（`is_active=False`）回傳 `None`
5. 回傳 dict 不含 `password` 欄位

`verify_secret_answer`：
1. 正確答案（不分大小寫）回傳 `True`
2. 大小寫不一致的答案仍回傳 `True`
3. 錯誤答案回傳 `False`

**執行測試**：
```bash
pytest tests/unit/ -v -k "register or login or auth or secret_answer or update_password"
pytest tests/integration/ -v -k "register or login or auth"
```
