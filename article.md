# Source notes for an X article

Write a public X article from these notes. Voice: David Brum, first person, plain and short. This is a maker post about a small Inkscape tool, not a changelog and not a troubleshooting log.

Link: https://github.com/davidbrum25/inkscape-fix-missing-images

Screenshots to attach, in this order, from the `media` folder:

1. `001_missingfiles.webp` — an Inkscape canvas with missing image placeholders and broken links.
2. `003_menuoptions.webp` — menu open at Extensions → Images → Fix Missing Images.
3. `002_popup.webp` — the extension dialog with options.
4. `004_feedbackmenu.webp` — the report dialog showing relinked files.
5. `005_success.webp` — the restored document with all images loaded and visible.

## TLDR, step by step

1. Inkscape does not have a native Link Manager or any way to batch relink missing images when files move or transfer between computers.

2. You either have to right-click each missing image one by one under Image Properties, or open the SVG in a code editor to find and replace paths.

3. So I wrote an extension called **Fix Missing Images**.

4. How it works: Extensions → Images → Fix Missing Images. Select a folder (or leave blank to search recursively in the SVG document's folder). It indexes the directory tree in a single fast pass and relinks all broken images at once.

5. Key features:
   - Portable relative paths (default) or absolute paths.
   - Case-insensitive filename matching across operating systems.
   - Intelligent subfolder matching when duplicate filenames exist in different directories.
   - Optional one-click Base64 embedding so files can never be lost again.
   - Dry run preview.

6. Tested on Inkscape 1.4 on Linux. Works cleanly.

7. The repo is public: https://github.com/davidbrum25/inkscape-fix-missing-images
   License is GPL-2.0-or-later, matching Inkscape's own extensions. Works with Inkscape 1.2+.

8. Install is a clone into the user extensions folder, then restart Inkscape:

   ```bash
   git clone https://github.com/davidbrum25/inkscape-fix-missing-images.git \
     ~/.config/inkscape/extensions/fix-missing-images
   ```

   On Windows that folder is `%APPDATA%\inkscape\extensions`.

## Facts to keep straight

- Author: David Brum. GitHub: davidbrum25.
- Menu path: Extensions → Images → Fix Missing Images.
- Single-pass recursive search for instant performance on large directories.
- Made with Inkscape 1.4. Requires 1.2+.

## Leave out of the post

Skip install friction, git credentials, file-size workarounds, and anything about how the files were uploaded. The story is the missing tool, the extension, and the link.
