"""
Service topology for the OpsEar simulated production environment.

This is intentionally small and fake — it exists so we can generate
realistic-looking telemetry and inject controlled incidents, not to
model a real distributed system.

    checkout-service
          |
          +---- payment-service ---- postgres (payment-db)
          |
          +---- inventory-service ---- postgres (inventory-db)
    user-service
    notification-service
"""

from dataclasses import dataclass, field


@dataclass
class Service:
    name: str
    depends_on: list = field(default_factory=list)
    baseline_latency_ms: float = 80.0
    baseline_error_rate: float = 0.005      # 0.5%
    baseline_cpu_pct: float = 30.0
    baseline_mem_pct: float = 40.0
    baseline_pool_utilization_pct: float = 20.0
    baseline_replicas: int = 3


SERVICES = {
    "checkout-service": Service(
        name="checkout-service",
        depends_on=["payment-service", "inventory-service"],
        baseline_latency_ms=120.0,
        baseline_error_rate=0.004,
        baseline_replicas=4,
    ),
    "payment-service": Service(
        name="payment-service",
        depends_on=["payment-db"],
        baseline_latency_ms=60.0,
        baseline_error_rate=0.003,
        baseline_pool_utilization_pct=25.0,
        baseline_replicas=3,
    ),
    "inventory-service": Service(
        name="inventory-service",
        depends_on=["inventory-db"],
        baseline_latency_ms=50.0,
        baseline_error_rate=0.002,
        baseline_replicas=2,
    ),
    "user-service": Service(
        name="user-service",
        depends_on=[],
        baseline_latency_ms=40.0,
        baseline_error_rate=0.002,
        baseline_replicas=2,
    ),
    "notification-service": Service(
        name="notification-service",
        depends_on=[],
        baseline_latency_ms=30.0,
        baseline_error_rate=0.001,
        baseline_replicas=2,
    ),
    # Datastores are modeled as services too, purely so metrics/logs
    # can reference them, but they have no HTTP-style metrics.
    "payment-db": Service(name="payment-db", depends_on=[]),
    "inventory-db": Service(name="inventory-db", depends_on=[]),
}

SERVICE_NAMES = list(SERVICES.keys())
