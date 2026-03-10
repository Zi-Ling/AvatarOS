#!/usr/bin/env python3
"""
Artifact System + History API 端到端测试脚本

测试链路：
  1. 直接写 DB（ExecutionSession + StepTraceRecord + ArtifactRecord）
  2. 打 API 验证接口返回
  3. 验证 download 接口文件存在性校验

用法：
  cd server
  python scripts/test_artifact_history.py [--base-url http://localhost:8000]
"""
import argparse
import json
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── 把 server/ 加入 sys.path ──────────────────────────────────────────
SERVER_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SERVER_DIR))


def setup_db():
    """初始化 DB（确保表存在）"""
    from app.db.database import init_db
    init_db()


def seed_data(tmp_file: Path):
    """写入测试数据，返回 (session_id, step_id, artifact_id)"""
    from app.db.database import engine
    from app.db.system import ExecutionSession
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceRecord
    from app.db.artifact_record import ArtifactRecord
    from sqlmodel import Session

    session_id  = f"test-session-{uuid.uuid4().hex[:8]}"
    step_id     = f"test-node-{uuid.uuid4().hex[:8]}"
    artifact_id = f"test-artifact-{uuid.uuid4().hex[:8]}"
    conv_id     = f"test-conv-{uuid.uuid4().hex[:8]}"

    now = datetime.now(timezone.utc)

    with Session(engine) as db:
        # 1. ExecutionSession
        es = ExecutionSession(
            id=session_id,
            conversation_id=conv_id,
            goal="测试：列出目录文件",
            status="completed",
            result_status="success",
            total_nodes=1,
            completed_nodes=1,
            failed_nodes=0,
            created_at=now,
            started_at=now,
            completed_at=now,
        )
        db.add(es)

        # 2. StepTraceRecord
        tr = StepTraceRecord(
            session_id=session_id,
            graph_id=f"graph-{uuid.uuid4().hex[:8]}",
            step_id=step_id,
            step_type="fs.list",
            status="success",
            started_at=now,
            ended_at=now,
            execution_time_s=0.42,
            retry_count=0,
            artifact_ids_json=json.dumps([artifact_id]),
            output_summary='{"files": ["a.txt", "b.csv"]}',
            created_at=now,
        )
        db.add(tr)

        # 3. ArtifactRecord（指向真实临时文件）
        ar = ArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            step_id=step_id,
            filename=tmp_file.name,
            storage_uri=str(tmp_file),
            size=tmp_file.stat().st_size,
            checksum="deadbeef",
            mime_type="text/plain",
            artifact_type="file",
            created_at=now,
        )
        db.add(ar)

        db.commit()

    print(f"  session_id  = {session_id}")
    print(f"  step_id     = {step_id}")
    print(f"  artifact_id = {artifact_id}")
    print(f"  conv_id     = {conv_id}")
    return session_id, step_id, artifact_id, conv_id


def check(label: str, cond: bool, detail: str = ""):
    mark = "✅" if cond else "❌"
    msg = f"  {mark} {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    if not cond:
        sys.exit(1)


def run_api_tests(base_url: str, session_id: str, step_id: str, artifact_id: str, conv_id: str):
    import urllib.request
    import urllib.error

    def get(path: str) -> dict:
        url = base_url.rstrip("/") + path
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"HTTP {e.code} {url}: {body}")

    print("\n── /history/sessions ──────────────────────────────────────")
    sessions = get("/history/sessions?limit=100")
    found = next((s for s in sessions if s["id"] == session_id), None)
    check("session 出现在列表中", found is not None)
    check("goal 正确", found["goal"] == "测试：列出目录文件")
    check("conversation_id 正确", found["conversation_id"] == conv_id)

    print("\n── /history/sessions?conversation_id=... ──────────────────")
    filtered = get(f"/history/sessions?conversation_id={conv_id}")
    check("按 conversation_id 过滤正确", len(filtered) == 1 and filtered[0]["id"] == session_id)

    print("\n── /history/sessions/{session_id} ─────────────────────────")
    detail = get(f"/history/sessions/{session_id}")
    check("detail.id 正确", detail["id"] == session_id)
    check("steps 非空", len(detail["steps"]) > 0)
    step = detail["steps"][0]
    check("step.step_id 正确", step["step_id"] == step_id)
    check("step.step_type 正确", step["step_type"] == "fs.list")
    check("step.artifact_ids 含 artifact_id", artifact_id in step["artifact_ids"])
    check("step.summary 非空", bool(step.get("summary")))
    check("step.timing.duration_s 正确", step["timing"]["duration_s"] == 0.42)

    print("\n── /artifacts/session/{session_id} ────────────────────────")
    arts = get(f"/artifacts/session/{session_id}")
    check("session artifacts 非空", len(arts) > 0)
    check("artifact_id 正确", arts[0]["artifact_id"] == artifact_id)

    print("\n── /artifacts/step/{step_id} ──────────────────────────────")
    arts2 = get(f"/artifacts/step/{step_id}")
    check("step artifacts 非空", len(arts2) > 0)
    check("artifact_id 正确", arts2[0]["artifact_id"] == artifact_id)

    print("\n── /artifacts/{artifact_id} ───────────────────────────────")
    art = get(f"/artifacts/{artifact_id}")
    check("filename 正确", art["filename"] is not None)
    check("size > 0", art["size"] > 0)
    check("mime_type 正确", art["mime_type"] == "text/plain")

    print("\n── /artifacts/{artifact_id}/download ──────────────────────")
    dl_url = base_url.rstrip("/") + f"/artifacts/{artifact_id}/download"
    with urllib.request.urlopen(dl_url, timeout=5) as r:
        content = r.read()
    check("download 返回文件内容", b"artifact test" in content)

    print("\n── download 不存在文件返回 410 ─────────────────────────────")
    # 写一条 storage_uri 指向不存在路径的记录
    from app.db.database import engine
    from app.db.artifact_record import ArtifactRecord
    from sqlmodel import Session
    ghost_id = f"ghost-{uuid.uuid4().hex[:8]}"
    with Session(engine) as db:
        db.add(ArtifactRecord(
            artifact_id=ghost_id,
            session_id=session_id,
            step_id=step_id,
            filename="ghost.txt",
            storage_uri="/nonexistent/path/ghost.txt",
            size=0,
            artifact_type="file",
        ))
        db.commit()
    try:
        get(f"/artifacts/{ghost_id}/download")
        check("ghost download 应返回 410", False, "未抛出异常")
    except RuntimeError as e:
        check("ghost download 返回 410", "410" in str(e), str(e))


def cleanup(session_id: str):
    """清理测试数据"""
    from app.db.database import engine
    from app.db.system import ExecutionSession
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceRecord
    from app.db.artifact_record import ArtifactRecord
    from sqlmodel import Session, select, delete

    with Session(engine) as db:
        db.exec(delete(ArtifactRecord).where(ArtifactRecord.session_id == session_id))
        db.exec(delete(StepTraceRecord).where(StepTraceRecord.session_id == session_id))
        db.exec(delete(ExecutionSession).where(ExecutionSession.id == session_id))
        db.commit()
    print(f"\n  🧹 测试数据已清理 (session_id={session_id})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--no-cleanup", action="store_true", help="保留测试数据")
    args = parser.parse_args()

    print("=" * 60)
    print("Artifact System + History API 端到端测试")
    print("=" * 60)

    print("\n[1] 初始化 DB...")
    setup_db()
    print("  ✅ DB 就绪")

    print("\n[2] 写入测试数据...")
    with tempfile.NamedTemporaryFile(
        suffix=".txt", delete=False, mode="wb"
    ) as f:
        f.write(b"artifact test content\n")
        tmp_path = Path(f.name)

    session_id, step_id, artifact_id, conv_id = seed_data(tmp_path)

    print(f"\n[3] 打 API ({args.base_url})...")
    try:
        run_api_tests(args.base_url, session_id, step_id, artifact_id, conv_id)
    finally:
        tmp_path.unlink(missing_ok=True)
        if not args.no_cleanup:
            cleanup(session_id)

    print("\n" + "=" * 60)
    print("✅ 全部通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
