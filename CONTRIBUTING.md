# Contributing

Report the target Ubuntu release, architecture, builder commit, exact command and the relevant redacted logs. Do not upload credentials, production configuration or session data. Check `VALIDATION.md` before proposing a supported/verified status change.

Source/patch pin updates require independent checksum/provenance review, explicit review of new patch rejects, and new full compilation/runtime tests for all three targets. Never disable checksum/signature checks to fix a failed download.

Run `python3 -m unittest discover -s tests -v` and `bash -n build.sh scripts/container.sh` before submitting changes. These checks do not compile PHP. Real builds are explicitly manual.

Keep changes to the build process separate from any proposal to publish binaries or run a public APT repository. Preserve downloaded upstream license notices in derived distributions.
