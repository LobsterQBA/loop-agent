# Hosting the walkthrough

[← Project overview](../README.md)

The public page is an **interactive replay**, not a hosted Python server. It displays three real
execution records generated from this repository. Visitors can choose a task, expand each event,
and download its JSON. They cannot enter arbitrary prompts or change stored facts on the hosted page.
Use the local Python app for that.

## Build and preview

```bash
python3 -m agent_system.build_site
python3 -m http.server 8000 --directory _site
```

Open localhost:8000. The builder runs calculate/save, recall, and a failed calculation in separate
Python processes against one temporary database. It saves the returned turns, memory snapshots, and
source commit in `examples.json`, then removes the temporary database. It copies only HTML, CSS, JS,
and the generated example data. Relative asset paths support the `/loop-agent/` Pages subdirectory.

The [deployment workflow](../.github/workflows/pages.yml) runs tests, lint, and the restart walkthrough
before building and uploading a Pages artifact. It deploys on pushes to `main`. Repository Pages settings
must select **GitHub Actions** as the source. See [GitHub's custom workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Visual direction

The UI uses a restrained application layout: task and result on the left, inspectable execution on the
right, and the saved-state snapshot below. Plain typography, muted colors, and compact controls keep
the example ahead of the surrounding interface. Observations open by default; other raw data is one
click away. The first recorded task loads automatically.

References, not copied assets or source:

- [Langfuse trace inspection](https://langfuse.com/docs/observability/overview): separating steps from their input/output evidence.
- [Linear's 2026 design refresh](https://linear.app/now/behind-the-latest-design-refresh): quiet navigation, consistent controls, and reduced visual noise.

This project intentionally uses a much smaller interface than those products. A three-example walkthrough
is enough to explain its control flow without adding dashboards, fake metrics, or unrelated settings.
