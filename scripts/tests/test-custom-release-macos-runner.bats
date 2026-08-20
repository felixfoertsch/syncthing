#!/usr/bin/env bats

setup() {
	REPO_ROOT="$(git rev-parse --show-toplevel)"
	WORKFLOW="$REPO_ROOT/.gitea/workflows/custom-release.yml"
	GITHUB_WORKFLOW="$REPO_ROOT/.github/workflows/custom-release.yml"
	RELEASE_SCRIPT="$REPO_ROOT/scripts/update-custom-release.sh"
	SYNC_SCRIPT="$REPO_ROOT/scripts/sync-upstream.sh"
}

@test "both hosts mirror upstream before building their own release" {
	run rg -n 'run: ./scripts/sync-upstream.sh' "$WORKFLOW" "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]
	[ "${#lines[@]}" -eq 2 ]

	run rg -n 'git push --force-with-lease=.*upstream|git push --force-with-lease=.*main' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'git apply patches/sync-stignore.patch patches/webui-build-marker.patch' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'main_parent=.*current_main\^' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'main_parent.*current_upstream' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'main_ahead_count=.*rev-list --count' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'main_ahead_count.*== "1"' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'GIT_AUTHOR_DATE=.*GIT_COMMITTER_DATE=' "$SYNC_SCRIPT"
	[ "$status" -eq 0 ]
}

@test "github custom release uses a github macos runner and github releases" {
	run rg -n 'runs-on:[[:space:]]*macos-14' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'gh release create' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_CREATE_GITEA_RELEASE: "0"' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_SIGN_DARWIN: "1"' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'tea|ffmini_macos_arm64' "$GITHUB_WORKFLOW"
	[ "$status" -ne 0 ]
}

@test "github imports signing secrets into a disposable keychain" {
	run rg -n 'DEVELOPER_ID_APPLICATION_P12_BASE64:.*secrets.DEVELOPER_ID_APPLICATION_P12_BASE64' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'DEVELOPER_ID_APPLICATION_P12_PASSWORD:.*secrets.DEVELOPER_ID_APPLICATION_P12_PASSWORD' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security import .* -P "\$DEVELOPER_ID_APPLICATION_P12_PASSWORD"' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n '::add-mask::\$keychain_password' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'if: always\(\)' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security delete-keychain "\$CUSTOM_RELEASE_KEYCHAIN_PATH"' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'rm -f "\$CUSTOM_RELEASE_CERTIFICATE_PATH"' "$GITHUB_WORKFLOW"
	[ "$status" -eq 0 ]
}

@test "custom release runs as one job on ffmini macos runner" {
	run rg -n 'runs-on:[[:space:]]*ffmini_macos_arm64' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'ubuntu-latest' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'actions/upload-artifact' "$WORKFLOW"
	[ "$status" -ne 0 ]
}

@test "custom release tea login setup is idempotent on persistent host runner" {
	run rg -n 'tea" logins delete actions >/dev/null 2>&1 \|\| true' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'tea" logins add --name actions' "$WORKFLOW"
	[ "$status" -eq 0 ]
}

@test "custom release workflow imports developer id signing material into temporary keychain" {
	run rg -n 'DEVELOPER_ID_APPLICATION_P12_BASE64' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'DEVELOPER_ID_APPLICATION_P12_PASSWORD' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'DEVELOPER_ID_APPLICATION_P12_BASE64 secret is required' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'DEVELOPER_ID_APPLICATION_P12_PASSWORD secret is required' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'security import .* -P "\$DEVELOPER_ID_APPLICATION_P12_PASSWORD"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security import .* -A ' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security find-identity -v -p codesigning "\$keychain_path"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security default-keychain -d user -s "\$keychain_path"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'previous_default_keychain=' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_PREVIOUS_DEFAULT_KEYCHAIN=\$previous_default_keychain' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_PREVIOUS_DYNAMIC_DEFAULT_KEYCHAIN' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'security default-keychain -s "\$CUSTOM_RELEASE_PREVIOUS_DEFAULT_KEYCHAIN"' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'security default-keychain -d dynamic' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'security find-identity -v -p codesigning$' "$WORKFLOW" "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'codesign_identity_sha1=' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'sed -n .*Developer ID Application' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_CODESIGN_IDENTITY=\$codesign_identity' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_CODESIGN_IDENTITY_SHA1=\$codesign_identity_sha1' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_KEYCHAIN_PASSWORD=\$keychain_password' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'codesign --force --dryrun --sign "\$codesign_identity" --keychain "\$keychain_path" --options runtime --timestamp "\$probe_binary"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_CODESIGN_IDENTITY: "Developer ID Application' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'security create-keychain' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'keychain_dir="\$HOME/Library/Keychains"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'rm -f "\$keychain_path"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'existing_keychains=\(\)' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security list-keychains -s "\$keychain_path"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security list-keychains -d dynamic' "$WORKFLOW"
	[ "$status" -ne 0 ]

	run rg -n 'security import' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'security delete-keychain' "$WORKFLOW"
	[ "$status" -eq 0 ]
}

@test "custom release carries per-target cgo mode" {
	run rg -n 'darwin/arm64/zip/1' "$WORKFLOW" "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'linux/amd64/tar/0' "$WORKFLOW" "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_CGO_ENABLED' "$WORKFLOW"
	[ "$status" -ne 0 ]
}

@test "custom release signs darwin assets with hardened runtime and timestamp" {
	run rg -n 'codesign_args=\(--force --sign "\$codesign_identity"\)' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n -- '--keychain "\$CUSTOM_RELEASE_KEYCHAIN_PATH"' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'codesign_args\+=\(--options runtime --timestamp\)' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'security unlock-keychain -p "\$CUSTOM_RELEASE_KEYCHAIN_PASSWORD" "\$CUSTOM_RELEASE_KEYCHAIN_PATH"' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'security find-identity -v -p codesigning "\$CUSTOM_RELEASE_KEYCHAIN_PATH"' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run awk '
		/codesign_args=\(--force --sign "\$codesign_identity"\)/ { sign = NR }
		/codesign_args\+=\(--keychain "\$CUSTOM_RELEASE_KEYCHAIN_PATH"\)/ { keychain = NR }
		/codesign_args\+=\(--options runtime --timestamp\)/ { options = NR }
		END { exit !(sign && keychain && options && sign < keychain && keychain < options) }
	' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'Developer ID Application' "$WORKFLOW" "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_CODESIGN_IDENTITY' "$WORKFLOW" "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]
}

@test "custom release validates signed darwin binaries before publishing" {
	run rg -n 'modernc-sqlite' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'codesign --verify --strict --verbose=2' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'TeamIdentifier=NG5W75WE8U|TeamIdentifier.*NG5W75WE8U' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_REQUIRE_GATEKEEPER_ASSESSMENT: "0"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'CUSTOM_RELEASE_SIGN_DARWIN: "1"' "$WORKFLOW"
	[ "$status" -eq 0 ]

	run rg -n 'require_gatekeeper_assessment="\$\{CUSTOM_RELEASE_REQUIRE_GATEKEEPER_ASSESSMENT:-0\}"' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'if \[\[ "\$require_gatekeeper_assessment" == "1" \]\]; then' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]

	run rg -n 'spctl -a -vv --type execute' "$RELEASE_SCRIPT"
	[ "$status" -eq 0 ]
}
