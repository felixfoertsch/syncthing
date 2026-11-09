// Copyright (C) 2026 The Syncthing Authors.
//
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this file,
// You can obtain one at https://mozilla.org/MPL/2.0/.

package auto

import (
	"compress/gzip"
	"io"
	"strings"
	"testing"
)

const customBuildMarker = "It syncs .stignore now!"

func TestCustomBuildMarkerIsEmbedded(t *testing.T) {
	asset, ok := Assets()["default/index.html"]
	if !ok {
		t.Fatal("default/index.html is missing from embedded GUI assets")
	}

	content := asset.Content
	if asset.Gzipped {
		reader, err := gzip.NewReader(strings.NewReader(asset.Content))
		if err != nil {
			t.Fatal(err)
		}
		defer reader.Close()

		data, err := io.ReadAll(reader)
		if err != nil {
			t.Fatal(err)
		}
		content = string(data)
	}

	if !strings.Contains(content, customBuildMarker) {
		t.Fatalf("embedded GUI assets do not contain custom build marker %q", customBuildMarker)
	}
}
