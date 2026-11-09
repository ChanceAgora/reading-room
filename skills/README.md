# Reading Room skills

Browse the complete skills here, including their reference guides and helper scripts. You can read them without installing the application.

| Skill | What it does |
| --- | --- |
| [bookshare-find](bookshare-find/SKILL.md) | Finds and compares accessible Bookshare editions before downloading. |
| [bookshare-download](bookshare-download/SKILL.md) | Guides authorized browser downloads, inspects the actual files, and prepares local intake. |
| [library-search](library-search/SKILL.md) | Searches the library, reads source passages, checks attribution, and drafts citations. |

`./bin/setup` creates project discovery links under `.agents/skills/`, pointing to these folders. Those generated links stay outside Git and source packages. Edit the files here; there is no second copy to keep in sync.

For use from other projects, the optional installer creates user-level links:

```sh
.venv/bin/python scripts/manage_skills.py install
```

Both installers preserve customized skills and report conflicts. See [Codex setup](../docs/codex.md) for discovery, installation/removal, browser sign-in, and example prompts. The skills use the checkout's application environment and library configuration; copying one skill folder alone does not install the backend.
