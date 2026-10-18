"""Read-only integration replicas (CDC from platform services)."""

from app.db.models.integration.iam_tenant_entitlement import TenantServiceEntitlement

__all__ = ["TenantServiceEntitlement"]
