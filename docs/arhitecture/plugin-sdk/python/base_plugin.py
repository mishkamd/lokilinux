"""
LokiLinux Plugin SDK — Python base classes.

Usage:
    from base_plugin import BasePlugin, PluginContext

    class MyPlugin(BasePlugin):
        def check(self) -> bool:
            return True

        def collect(self) -> dict:
            self.ctx.emit_metric("my.metric", 42.0)
            return {"data": []}

    Plugin = MyPlugin
"""

import abc
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginContext:
    """Runtime context injected into every plugin by the agent sandbox."""

    plugin_id: str
    agent_id: str
    config: dict[str, Any] = field(default_factory=dict)
    data_dir: Path = Path("/var/lib/lokilinux/plugins")
    _logger: logging.Logger = field(init=False)

    def __post_init__(self) -> None:
        self._logger = logging.getLogger(f"plugin.{self.plugin_id}")

    def log(self, message: str, level: str = "info") -> None:
        getattr(self._logger, level)(message)

    def emit_metric(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Write a metric event to stdout for the agent to forward."""
        print(json.dumps({"type": "metric", "name": name, "value": value, "labels": labels or {}}))
        sys.stdout.flush()

    def emit_alert(self, title: str, message: str, severity: str = "INFO") -> None:
        """Write an alert event to stdout for the agent to forward."""
        print(json.dumps({"type": "alert", "title": title, "message": message, "severity": severity}))
        sys.stdout.flush()


class BasePlugin(abc.ABC):
    """Base class every LokiLinux plugin must subclass.

    The agent sandbox calls:
      1. check()    — gate: skip collect() if False
      2. collect()  — gather data; return dict forwarded to control plane
      3. on_install / on_uninstall — lifecycle hooks (optional)

    Assign the concrete class to the module-level `Plugin` name so the loader
    can discover it:  `Plugin = MyPlugin`
    """

    def __init__(self, ctx: PluginContext) -> None:
        self.ctx = ctx

    @abc.abstractmethod
    def check(self) -> bool:
        """Return True if the integration target is reachable/configured."""
        ...

    @abc.abstractmethod
    def collect(self) -> dict[str, Any]:
        """Collect data from the integration; return serialisable dict."""
        ...

    def on_install(self) -> None:
        """Called once after the plugin is installed on an agent."""

    def on_uninstall(self) -> None:
        """Called once before the plugin is removed from an agent."""


# ── Zabbix example (mirrors docs/LOKILINUX_DOCKER_DEPLOYMENT.md §5.4) ─────────

class ZabbixConnectorPlugin(BasePlugin):
    """Read-only Zabbix host inventory connector."""

    def check(self) -> bool:
        return bool(self.ctx.config.get("zabbix_url"))

    def collect(self) -> dict[str, Any]:
        self.ctx.log(f"Collecting from {self.ctx.config['zabbix_url']}")
        # Real impl: POST zabbix_url/api_jsonrpc.php with user/pass from config
        # ponytail: HTTP call omitted — add aiohttp when agent SDK goes async
        return {"source": "zabbix", "hosts": []}

    def on_install(self) -> None:
        self.ctx.log("Zabbix connector installed", level="info")


Plugin = ZabbixConnectorPlugin  # loader entry point (replace in your plugin)
