package org.amnesia.assistant;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Android Storage Access Framework bridge for one imported .amod archive. */
public final class FilePickerBridge {
    public interface Callback {
        void onComplete(String path, String error, boolean cancelled);
    }

    public static final int REQUEST_CODE = 0xA001;
    private static Callback callback;
    private static String stagingDirectory;

    private FilePickerBridge() {
    }

    public static void openAmodPicker(
            Activity activity,
            String stagingPath,
            Callback completion) {
        callback = completion;
        stagingDirectory = stagingPath;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        // Providers often report custom archives as application/octet-stream;
        // filter the final selection by .amod and archive validation in Python.
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
        activity.startActivityForResult(intent, REQUEST_CODE);
    }

    /** Call this from PythonSDLActivity.onActivityResult. */
    public static boolean handleActivityResult(
            Activity activity,
            int requestCode,
            int resultCode,
            Intent data) {
        if (requestCode != REQUEST_CODE) {
            return false;
        }

        Callback completion = callback;
        callback = null;
        String targetDirectory = stagingDirectory;
        stagingDirectory = null;
        if (completion == null) {
            return true;
        }
        if (resultCode != Activity.RESULT_OK || data == null || data.getData() == null) {
            completion.onComplete(null, null, true);
            return true;
        }

        Uri uri = data.getData();
        File target = null;
        try {
            File directory = new File(targetDirectory);
            if (!directory.isDirectory() && !directory.mkdirs()) {
                throw new IllegalStateException("The import staging directory is unavailable.");
            }
            target = File.createTempFile("amod-import-", ".amod", directory);
            try (InputStream input = activity.getContentResolver().openInputStream(uri);
                 OutputStream output = new FileOutputStream(target)) {
                if (input == null) {
                    throw new IllegalStateException("The selected document could not be opened.");
                }
                byte[] buffer = new byte[1024 * 1024];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    output.write(buffer, 0, read);
                }
            }
            completion.onComplete(target.getAbsolutePath(), null, false);
        } catch (Exception error) {
            if (target != null) {
                //noinspection ResultOfMethodCallIgnored
                target.delete();
            }
            completion.onComplete(null, error.getMessage(), false);
        }
        return true;
    }
}
