# server/app/services/workflow/template_store.py
"""
模板 CRUD + 版本管理 + DAG/输出键校验 + content_hash 去重。

正确性属性：P1（DAG 无环）、P2（往返一致性）、P6（输出键引用合法）。
"""
from __future__ import annotations

import graphlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.db.database import engine
from .models import (
    WorkflowTemplate,
    WorkflowTemplateVersion,
    WorkflowInstance,
    WorkflowTrigger,
    WorkflowStepDef,
    WorkflowEdgeDef,
    compute_content_hash,
    _now,
    _uuid,
)

logger = logging.getLogger(__name__)

MAX_VERSIONS_PER_TEMPLATE = 50


class TemplateStore:
    """模板 CRUD + 版本管理"""

    # ------------------------------------------------------------------
    # 校验方法
    # ------------------------------------------------------------------

    @staticmethod
    def validate_dag(steps: list[dict], edges: list[dict]) -> None:
        """用 graphlib.TopologicalSorter 检测环（P1）。有环抛 CycleError。"""
        step_ids = {s["step_id"] for s in steps}
        graph: dict[str, set[str]] = {sid: set() for sid in step_ids}
        for e in edges:
            src, tgt = e["source_step_id"], e["target_step_id"]
            if src in step_ids and tgt in step_ids:
                graph[tgt].add(src)  # tgt depends on src
        ts = graphlib.TopologicalSorter(graph)
        # prepare() 会在有环时抛 graphlib.CycleError
        ts.prepare()

    @staticmethod
    def validate_output_refs(steps: list[dict], edges: list[dict]) -> None:
        """检查每条 edge 的 source_output_key 存在于源步骤 outputs 中（P6）。"""
        step_outputs: dict[str, set[str]] = {}
        for s in steps:
            keys = set()
            for o in s.get("outputs", []):
                keys.add(o["key"])
            step_outputs[s["step_id"]] = keys

        for e in edges:
            src_id = e["source_step_id"]
            src_key = e["source_output_key"]
            available = step_outputs.get(src_id, set())
            if src_key not in available:
                raise ValueError(
                    f"Edge 引用了不存在的输出键: step={src_id}, key={src_key}, "
                    f"可用键: {available}"
                )

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create_template(
        self,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
        steps: list[dict] | None = None,
        edges: list[dict] | None = None,
        parameters: list[dict] | None = None,
        global_failure_policy: str = "fail_fast",
    ) -> WorkflowTemplate:
        """创建模板 + 第一个版本。"""
        steps = steps or []
        edges = edges or []
        parameters = parameters or []
        tags = tags or []

        # 校验
        if steps:
            self.validate_dag(steps, edges)
        if edges:
            self.validate_output_refs(steps, edges)

        content_hash = compute_content_hash(
            steps, edges, parameters, global_failure_policy
        )

        with Session(engine) as db:
            template = WorkflowTemplate(
                name=name, description=description, tags=tags,
            )
            db.add(template)
            db.flush()

            version = WorkflowTemplateVersion(
                template_id=template.id,
                version_number=1,
                steps=steps,
                edges=edges,
                parameters=parameters,
                global_failure_policy=global_failure_policy,
                content_hash=content_hash,
            )
            db.add(version)
            db.flush()

            template.latest_version_id = version.id
            db.add(template)
            db.commit()
            db.refresh(template)

        logger.info(f"[TemplateStore] Created template {template.id} v1")
        return template

    # ------------------------------------------------------------------
    # 更新（自动创建新版本 + content_hash 去重）
    # ------------------------------------------------------------------

    def update_template(
        self,
        template_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        steps: Optional[list[dict]] = None,
        edges: Optional[list[dict]] = None,
        parameters: Optional[list[dict]] = None,
        global_failure_policy: Optional[str] = None,
    ) -> WorkflowTemplateVersion:
        """更新模板，自动创建新版本。相同内容不创建新版本。"""
        with Session(engine) as db:
            template = db.get(WorkflowTemplate, template_id)
            if not template or template.is_deleted:
                raise ValueError(f"模板不存在: {template_id}")

            # 获取当前最新版本作为基线
            latest = db.get(WorkflowTemplateVersion, template.latest_version_id)
            new_steps = steps if steps is not None else (latest.steps if latest else [])
            new_edges = edges if edges is not None else (latest.edges if latest else [])
            new_params = parameters if parameters is not None else (latest.parameters if latest else [])
            new_policy = global_failure_policy or (latest.global_failure_policy if latest else "fail_fast")

            # 校验
            if new_steps:
                self.validate_dag(new_steps, new_edges)
            if new_edges:
                self.validate_output_refs(new_steps, new_edges)

            # content_hash 去重
            new_hash = compute_content_hash(new_steps, new_edges, new_params, new_policy)
            if latest and latest.content_hash == new_hash:
                logger.info(f"[TemplateStore] 内容未变化，跳过版本创建")
                return latest

            # 计算新版本号
            max_ver = db.exec(
                select(WorkflowTemplateVersion.version_number)
                .where(WorkflowTemplateVersion.template_id == template_id)
                .order_by(WorkflowTemplateVersion.version_number.desc())  # type: ignore
            ).first() or 0
            new_version_number = max_ver + 1

            version = WorkflowTemplateVersion(
                template_id=template_id,
                version_number=new_version_number,
                steps=new_steps,
                edges=new_edges,
                parameters=new_params,
                global_failure_policy=new_policy,
                content_hash=new_hash,
            )
            db.add(version)
            db.flush()

            # 更新模板元数据
            if name is not None:
                template.name = name
            if description is not None:
                template.description = description
            if tags is not None:
                template.tags = tags
            template.latest_version_id = version.id
            template.updated_at = _now()
            db.add(template)

            # 版本上限清理
            self._cleanup_old_versions(db, template_id)

            db.commit()
            db.refresh(version)

        logger.info(f"[TemplateStore] Updated template {template_id} → v{new_version_number}")
        return version

    def _cleanup_old_versions(self, db: Session, template_id: str) -> None:
        """版本上限 50，超出时删除最旧且未被引用的版本。"""
        versions = db.exec(
            select(WorkflowTemplateVersion)
            .where(WorkflowTemplateVersion.template_id == template_id)
            .order_by(WorkflowTemplateVersion.version_number.desc())  # type: ignore
        ).all()

        if len(versions) <= MAX_VERSIONS_PER_TEMPLATE:
            return

        # 收集被引用的 version_id
        referenced = set()
        instances = db.exec(
            select(WorkflowInstance.template_version_id)
            .where(WorkflowInstance.template_id == template_id)
        ).all()
        referenced.update(instances)
        triggers = db.exec(
            select(WorkflowTrigger.template_version_id)
            .where(WorkflowTrigger.template_id == template_id)
            .where(WorkflowTrigger.template_version_id.isnot(None))  # type: ignore
        ).all()
        referenced.update(triggers)

        # 从最旧开始删除未引用的版本
        to_delete = versions[MAX_VERSIONS_PER_TEMPLATE:]
        for v in to_delete:
            if v.id not in referenced:
                db.delete(v)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get_template(template_id: str) -> Optional[WorkflowTemplate]:
        with Session(engine) as db:
            t = db.get(WorkflowTemplate, template_id)
            if t and t.is_deleted:
                return None
            return t

    @staticmethod
    def list_templates(tags: list[str] | None = None) -> list[WorkflowTemplate]:
        with Session(engine) as db:
            stmt = select(WorkflowTemplate).where(WorkflowTemplate.is_deleted == False)  # noqa: E712
            results = db.exec(stmt).all()
            if tags:
                tag_set = set(tags)
                results = [t for t in results if tag_set.intersection(t.tags or [])]
            return list(results)

    @staticmethod
    def get_version(version_id: str) -> Optional[WorkflowTemplateVersion]:
        with Session(engine) as db:
            return db.get(WorkflowTemplateVersion, version_id)

    @staticmethod
    def list_versions(template_id: str) -> list[WorkflowTemplateVersion]:
        with Session(engine) as db:
            return list(db.exec(
                select(WorkflowTemplateVersion)
                .where(WorkflowTemplateVersion.template_id == template_id)
                .order_by(WorkflowTemplateVersion.version_number.desc())  # type: ignore
            ).all())

    # ------------------------------------------------------------------
    # 删除（软删除）
    # ------------------------------------------------------------------

    @staticmethod
    def delete_template(template_id: str) -> None:
        """软删除模板。"""
        with Session(engine) as db:
            t = db.get(WorkflowTemplate, template_id)
            if t:
                t.is_deleted = True
                t.updated_at = _now()
                db.add(t)
                db.commit()

    # ------------------------------------------------------------------
    # 克隆
    # ------------------------------------------------------------------

    def clone_template(self, template_id: str, new_name: str) -> WorkflowTemplate:
        """克隆模板（基于最新版本创建新模板）。"""
        with Session(engine) as db:
            original = db.get(WorkflowTemplate, template_id)
            if not original or original.is_deleted:
                raise ValueError(f"模板不存在: {template_id}")
            latest = db.get(WorkflowTemplateVersion, original.latest_version_id)
            if not latest:
                raise ValueError(f"模板无版本: {template_id}")

        return self.create_template(
            name=new_name,
            description=original.description,
            tags=list(original.tags or []),
            steps=list(latest.steps or []),
            edges=list(latest.edges or []),
            parameters=list(latest.parameters or []),
            global_failure_policy=latest.global_failure_policy,
        )
