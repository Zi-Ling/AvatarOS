# app/avatar/skills/builtin/email.py

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# email.send
# ============================================================================

class EmailSendInput(SkillInput):
    smtp_host: str = Field(..., description="SMTP host.")
    smtp_port: int = Field(..., description="SMTP port.")
    username: str = Field(..., description="SMTP username.")
    password: str = Field(..., description="SMTP password.")
    to_addr: str = Field(..., description="Recipient email.")
    subject: str = Field(..., description="Subject.")
    body: str = Field(..., description="Body text.")
    from_addr: Optional[str] = Field(None, description="From address.")
    use_tls: bool = Field(True, description="Use TLS.")

class EmailSendOutput(SkillOutput):
    to_addr: str
    subject: str

@register_skill
class EmailSendSkill(BaseSkill[EmailSendInput, EmailSendOutput]):
    spec = SkillSpec(
        name="email.send",
        api_name="email.send",
        aliases=["mail.send", "smtp.send", "send_email"],
        description="Send a simple email via SMTP. 发送电子邮件。",
        category=SkillCategory.WEB,
        input_model=EmailSendInput,
        output_model=EmailSendOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.WEB,
            capabilities={SkillCapability.WRITE},
            risk_level="high"
        ),
        
        synonyms=[
            "send email",
            "send mail",
            "email message",
            "发送邮件",
            "发送电子邮件",
            "发邮件"
        ],
        examples=[
            {"description": "Send email via SMTP", "params": {"smtp_host": "smtp.example.com", "smtp_port": 587, "username": "user", "password": "pass", "to_addr": "recipient@example.com", "subject": "Hello", "body": "Message body"}}
        ],
        permissions=[SkillPermission(name="net_access", description="Send emails")],
        tags=["email", "smtp", "邮件", "发送", "电子邮件"]
    )

    async def run(self, ctx: SkillContext, params: EmailSendInput) -> EmailSendOutput:
        from_addr = params.from_addr or params.username
        
        if ctx.dry_run:
            return EmailSendOutput(
                success=True,
                message="[dry_run]",
                to_addr=params.to_addr,
                subject=params.subject
            )

        try:
            msg = EmailMessage()
            msg["From"] = from_addr
            msg["To"] = params.to_addr
            msg["Subject"] = params.subject
            msg.set_content(params.body)

            # Sync SMTP call (should be async in future)
            with smtplib.SMTP(params.smtp_host, params.smtp_port, timeout=30) as server:
                if params.use_tls: server.starttls()
                server.login(params.username, params.password)
                server.send_message(msg)
            
            return EmailSendOutput(
                success=True,
                message=f"Sent to {params.to_addr}",
                to_addr=params.to_addr,
                subject=params.subject
            )
        except Exception as e:
            return EmailSendOutput(success=False, message=str(e), to_addr=params.to_addr, subject=params.subject)
