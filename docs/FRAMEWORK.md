# T Forensic Framework

T Forensic is an **analysis framework**, not a read-only viewer only.

## Golden rule

**Original evidence is never modified.**  
Writable work uses:

| Area | Purpose |
|------|---------|
| `case/lab/` | Sandbox: working copies, carve output, plugin products |
| `xmount --cache` | Virtual-write overlay (disk writes hit cache file only) |
| `case/exports/`, `reports/` | Analyst products |

## Pieces

1. **Plugins** — Python classes under `~/.tforensic/plugins/` or built-ins (`hash_sweep`, `strings_hunt`, `timeline_export`, `correlate`)
2. **Lab** — `tforensic lab enable [--virtual-write]`
3. **Playbooks** — JSON pipelines (`quick_triage`, `deep_lab`)

## CLI

```bash
tforensic lab enable --virtual-write
tforensic lab status
tforensic lab copy /path/to/exported.bin

tforensic plugin list
tforensic plugin run strings_hunt
tforensic plugin run correlate

tforensic playbook list
tforensic playbook run quick_triage
```

## Write a plugin

```python
# ~/.tforensic/plugins/my_mod.py
from tforensic.framework.plugin import Plugin, PluginContext, PluginResult

class MyMod(Plugin):
    name = "my_mod"
    requires_lab = True
    description = "Does something useful"

    def run(self, ctx: PluginContext) -> PluginResult:
        out = ctx.write_lab("out/result.txt", "analysis product\n")
        ctx.add_artifact("custom", "My finding", str(out))
        return PluginResult(ok=True, plugin=self.name, summary="done", files_written=[str(out)])
```

## Disk virtual-write

```bash
tforensic lab enable --virtual-write
# then mount with cache from lab status:
tforensic mount evidence.E01 --cache ~/.tforensic/cases/<id>/lab/virtual-write.cache
```

Or use the **Lab** tab / Disk tab cache field in the UI.
