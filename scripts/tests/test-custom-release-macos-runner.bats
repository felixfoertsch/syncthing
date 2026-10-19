#!/usr/bin/env bats

@test "GitHub retains signed Darwin ARM64 and Linux archives on both channels" {
	workflow="$BATS_TEST_DIRNAME/../../.github/workflows/custom-release.yml"
	grep -F 'runs-on: macos-14' "$workflow"
	grep -F 'channel: [stable, nightly]' "$workflow"
	grep -F 'runs-on: macos-14' "$workflow"
	grep -F 'darwin/arm64/zip/1 linux/amd64/tar/0 linux/arm64/tar/0' "$BATS_TEST_DIRNAME/../build-candidate.sh"
	grep -F 'Sign verified archive without executing candidate' "$workflow"
	grep -F 'codesign --force --dryrun' "$workflow"
	grep -F 'if: always()' "$workflow"
	grep -F 'security delete-keychain' "$workflow"
}

@test "real Git release and reconstruction regressions pass" {
	run python3 "$BATS_TEST_DIRNAME/test-custom-release.py"
	[ "$status" -eq 0 ]
}
