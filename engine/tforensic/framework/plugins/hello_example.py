"""Example user plugin — copy to ~/.tforensic/plugins/hello.py to load."""
from tforensic.framework.plugin import Plugin, PluginContext, PluginResult


class HelloPlugin(Plugin):
    name = "hello"
    version = "0.1"
    description = "Example plugin that writes a hello file into lab/"
    requires_lab = True

    def run(self, ctx: PluginContext) -> PluginResult:
        path = ctx.write_lab("out/hello.txt", "Hello from T Forensic framework plugin.\n")
        ctx.add_artifact("demo", "Hello plugin ran", str(path))
        return PluginResult(
            ok=True,
            plugin=self.name,
            summary=f"wrote {path}",
            files_written=[str(path)],
        )
