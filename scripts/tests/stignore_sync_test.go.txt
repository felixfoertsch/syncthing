// Copyright (C) 2026 The Syncthing Authors.
//
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this file,
// You can obtain one at https://mozilla.org/MPL/2.0/.

package model

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/syncthing/syncthing/lib/fs"
	"github.com/syncthing/syncthing/lib/ignore"
	"github.com/syncthing/syncthing/lib/protocol"
)

// Do not call ScanFolder or LoadIgnores after receiving .stignore: either would
// hide a missing automatic reload. Disable both watcher and periodic scans.
func TestStignoreSyncRemoteReload(t *testing.T) {
	w, fcfg := newDefaultCfgWrapper(t)
	fcfg.FSWatcherEnabled = false
	fcfg.RescanIntervalS = 0
	setFolder(t, w, fcfg)
	m, fc := setupModelWithConnectionFromWrapper(t, w)
	tfs := fcfg.Filesystem()
	defer cleanupModelAndRemoveDir(m, tfs.URI())

	writeFile(t, tfs, "first.txt", []byte("first local file"))
	writeFile(t, tfs, "second.txt", []byte("second local file"))
	must(t, m.ScanFolder(fcfg.ID))

	waitFor := func(description string, check func() bool) {
		t.Helper()
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			if check() {
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
		t.Fatal("remote .stignore did not trigger a rescan: " + description)
	}
	isIgnored := func(name string, want bool) bool {
		fi, ok := m.testCurrentFolderFile(fcfg.ID, name)
		return ok && fi.IsInvalid() == want && !fi.IsDeleted()
	}
	for _, name := range []string{"first.txt", "second.txt"} {
		if !isIgnored(name, false) {
			t.Fatalf("initial file %s was not scanned", name)
		}
	}

	firstRules := []byte("first.txt\n")
	fc.addFile(".stignore", 0o644, protocol.FileInfoTypeFile, firstRules)
	fc.sendIndexUpdate()
	waitFor("creation", func() bool {
		return equalContents(tfs, ".stignore", firstRules) == nil &&
			isIgnored("first.txt", true) && isIgnored("second.txt", false)
	})

	previous, _ := m.testCurrentFolderFile(fcfg.ID, ".stignore")
	secondRules := []byte("second.txt\n// changed remotely\n")
	fc.updateFile(".stignore", 0o644, protocol.FileInfoTypeFile, secondRules)
	// A remote update may retain the previous mtime. Receiving new content
	// must invalidate the ignore cache instead of silently keeping old rules.
	fc.mut.Lock()
	for i := range fc.files {
		if fc.files[i].Name == ".stignore" {
			fc.files[i].ModifiedS = previous.ModifiedS
			fc.files[i].ModifiedNs = previous.ModifiedNs
		}
	}
	fc.mut.Unlock()
	fc.sendIndexUpdate()
	waitFor("replacement", func() bool {
		return equalContents(tfs, ".stignore", secondRules) == nil &&
			isIgnored("first.txt", false) && isIgnored("second.txt", true)
	})

	fc.deleteFile(".stignore")
	fc.sendIndexUpdate()
	waitFor("deletion", func() bool {
		_, err := tfs.Lstat(".stignore")
		return fs.IsNotExist(err) && isIgnored("first.txt", false) && isIgnored("second.txt", false)
	})
}

func TestStignoreSyncIgnoreRules(t *testing.T) {
	for _, tc := range []struct {
		name, rules string
		ignored     bool
	}{
		{"empty", "", false},
		{"normal patterns", "*.tmp\nprivate/\n", false},
		{"dotfile wildcard", ".*\n", true},
		{"allowlist without exception", "!/public\n*\n", true},
		{"explicit root exception", "!/.stignore\n*\n", false},
		{"explicit opt out", "/.stignore\n", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			matcher := ignore.New(fs.NewFilesystem(fs.FilesystemTypeBasic, t.TempDir()))
			must(t, matcher.Parse(strings.NewReader(tc.rules), ".stignore"))
			if got := matcher.Match(".stignore").IsIgnored(); got != tc.ignored {
				t.Fatalf(".stignore ignored = %v, want %v", got, tc.ignored)
			}
			for _, name := range []string{".stfolder", ".stfolder/marker", ".stversions", ".stversions/old", fs.TempName(".stignore")} {
				if !matcher.Match(name).IsIgnored() {
					t.Fatalf("protected path %s became syncable", name)
				}
			}
		})
	}
}

func TestStignoreSyncRequestAndProtectedPaths(t *testing.T) {
	m, _, fcfg := setupModelWithConnection(t)
	tfs := fcfg.Filesystem()
	defer cleanupModelAndRemoveDir(m, tfs.URI())

	content := []byte("*.tmp\n")
	writeFile(t, tfs, ".stignore", content)
	must(t, m.ScanFolder(fcfg.ID))
	fi, ok := m.testCurrentFolderFile(fcfg.ID, ".stignore")
	if !ok || fi.IsInvalid() || fi.IsDeleted() {
		t.Fatal("local .stignore was not indexed as a regular file")
	}
	hash := sha256.Sum256(content)
	res, err := m.Request(device1Conn, &protocol.Request{
		Folder: fcfg.ID, Name: ".stignore", Size: len(content), Hash: hash[:],
	})
	must(t, err)
	defer res.Close()
	if !bytes.Equal(res.Data(), content) {
		t.Fatal("peer did not receive the .stignore contents")
	}
	for _, name := range []string{".stfolder", ".stfolder/marker", ".stversions", ".stversions/old"} {
		res, err := m.Request(device1Conn, &protocol.Request{Folder: fcfg.ID, Name: name, Size: 1})
		if res != nil {
			res.Close()
			t.Errorf("served protected path %s", name)
		}
		if !errors.Is(err, protocol.ErrInvalid) {
			t.Errorf("request for protected path %s: got %v, want ErrInvalid", name, err)
		}
	}
}
