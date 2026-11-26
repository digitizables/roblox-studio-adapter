# Playtest evidence

`evidence_record` turns a `PlaytestReport` into JSON. The field list is [`evidence.schema.json`](evidence.schema.json). Schema id: `roblox-studio-adapter.evidence/1`.

```python
from roblox_studio_adapter.evidence import evidence_record

report = agent.playtest.run(
    seconds=3,
    expect_contains=["spawn ready"],
    expect_absent=["spawn failed"],
)
record = evidence_record(
    report,
    studio_id=agent.session.studio_id,
    intent_id="intent:verify-spawn",
)
```

`agent.loop.change_and_verify(..., intent_id="intent:verify-spawn")` already includes this object as `result["evidence"]`. `result["playtest"]` is still the Python report. Persist `result["evidence"]`.

## Checks

| `op` | When it is added | Passes when |
| --- | --- | --- |
| `error_free` | `forbid_errors` is true (the default) | the delta has no error lines |
| `contains` | each `expect_contains` entry, id `output.contains.N` | the delta contains that string |
| `absent` | each `expect_absent` entry, id `output.absent.N` | the delta does not contain that string |

`N` is the 1-based position in the list you passed. The needle is copied onto `expect`. Empty strings are rejected before the playtest starts.

`passed` is true when every check passed. It is null when `forbid_errors` is false, both lists are empty, and there are no probes: the run was an observation. `failures` repeats the `detail` of each failed check.

## Probes

`probes` run while the playtest is still up, before `stop` deletes the Server and Client copies. Each item is `{"id", "expression", "datamodel"}` with `datamodel` of `Server` or `Client`. `expression` is one Luau expression. `equals` fails the check `probe.<id>` when the JSON value differs. A probe that raises is a failed check. The value is stored on the record even when the check passes. Empty `probes` is an empty array.

## Console

The record stores a console excerpt, at most 10 error lines, and at most 10 warning lines. Each of those lines is clipped at 500 characters. The excerpt is clipped at 4000 characters, keeping the head and the tail. Counts still report the full delta. The full text remains on `report.console.text` until the process drops it.

`console.reset` is true when the pre-play snapshot was not found in the later log. The checks then ran against that whole later log. A caller that needs an isolated delta should treat the verdict as weaker. PROVE writes `inconclusive` in that case.

## Video

`playtest.record` returns the stop payload parsed by `parse_video_capture`:

- `status`: `completed`, `partial`, or `unknown`
- `recording_id`
- `artifacts.video`, `artifacts.manifest`, `artifacts.frame_times` (null when the payload has no path)
- `warnings`
- `text` (the raw tool result)

`partial` means capture ended early. It does not mean gameplay ended. `record` leaves the playtest running. `run` does not start a recording. A worker that recorded can place that object on a later evidence record's `artifacts.video`.

Screenshot paths from `run` are listed on `artifacts.screenshots`. The image bytes are files, not base64.
