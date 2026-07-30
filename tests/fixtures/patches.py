"""Fixtures: GitHub-style patch bodies (no ---/+++ headers — parser wraps them)."""

MULTI_HUNK_PATCH = """\
@@ -1,3 +1,4 @@ def greet():
 line1
-line2
+line2 changed
 line3
+line4
@@ -20,2 +21,3 @@
 ctx
+added
 ctx2
"""

RENAMED_PATCH = """\
@@ -1,1 +1,1 @@
-old content
+new content
"""

LOCKFILE_PATCH = """\
@@ -1,2 +1,3 @@
 {
-  "x": 1
+  "x": 1,
+  "y": 2
 }
"""

PURE_DELETE_PATCH = """\
@@ -1,3 +0,0 @@
-gone1
-gone2
-gone3
"""

MINIFIED_PATCH = """\
@@ -1 +1 @@
-a
+b
"""
