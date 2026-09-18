# Native file-picker overlays

The Ren'Py game owns the one-file import lifecycle in `game/file_picker.py`.
These overlays provide the platform callbacks and copy the selected document to
an app-private temporary file before handing it to Python.

They are not ordinary Ren'Py game assets and must be added to the generated
platform projects:

- Android: add `android/FilePickerBridge.java` to the RAPT Android activity
  sources and forward `PythonSDLActivity.onActivityResult` to
  `FilePickerBridge.handleActivityResult` before/alongside the existing
  activity-result handling, for example:

  ```java
  if (FilePickerBridge.handleActivityResult(this, requestCode, resultCode, data)) {
      return;
  }
  ```
- iOS: add `ios/RenpyFilePicker.h` and `ios/RenpyFilePicker.m` to the generated
  Xcode project. Add the UIKit and UniformTypeIdentifiers frameworks if the
  generated project does not already link them.

The Python adapters fail explicitly when these bridge classes are absent. They
do not fall back to scanning `mods/inbox`.

Both bridges implement import/copy semantics. They do not return Android
`content://` or external iOS security-scoped URLs to game code. The returned
path is a temporary file owned by the Python import operation and is deleted
whether installation succeeds or fails.
