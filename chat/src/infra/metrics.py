import threading
import time

# ─────────────────────────────────────
# LLM 状态（内存记录，不发网络请求）
# ─────────────────────────────────────
_llm_lock = threading.Lock()

_llm_status = {
    "status":     "unknown",   # ok / error / unknown
    "last_ok":    None,        # 最近一次成功时间
    "last_error": None,        # 最近一次失败时间
    "error_msg":  None,
}

def mark_llm_ok():
    with _llm_lock:
        _llm_status["status"]   = "ok"
        _llm_status["last_ok"]  = time.time()

def mark_llm_error(msg: str):
    with _llm_lock:
        _llm_status["status"]     = "error"
        _llm_status["last_error"] = time.time()
        _llm_status["error_msg"]  = msg

def get_llm_status() -> dict:
    with _llm_lock:
        return _llm_status.copy()

# ─────────────────────────────────────
# DB 写入失败计数
# ─────────────────────────────────────
_db_lock = threading.Lock()
_db_write_failures: int = 0

def mark_db_write_failure():
    global _db_write_failures
    with _db_lock:
        _db_write_failures += 1

def get_db_write_failures() -> int:
    with _db_lock:
        return _db_write_failures

# ─────────────────────────────────────
# Timer
# ─────────────────────────────────────
class Timer:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.ms = (time.perf_counter() - self._start) * 1000
