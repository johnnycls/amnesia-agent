#import "RenpyFilePicker.h"

#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

@interface RenpyFilePicker ()
@property(nonatomic, strong) id<RenpyFilePickerDelegate> delegate;
@end

@implementation RenpyFilePicker

- (void)openAmodPickerWithDelegate:(id<RenpyFilePickerDelegate>)delegate {
    self.delegate = delegate;

    UIDocumentPickerViewController *picker;
    if (@available(iOS 14.0, *)) {
        NSArray<UTType *> *types = @[
            [UTType typeWithIdentifier:@"com.pkware.zip-archive"] ?: UTTypeData
        ];
        picker = [[UIDocumentPickerViewController alloc]
            initForOpeningContentTypes:types
            asCopy:YES];
    } else {
        picker = [[UIDocumentPickerViewController alloc]
            initWithDocumentTypes:@[@"com.pkware.zip-archive", @"public.data"]
            inMode:UIDocumentPickerModeImport];
    }

    picker.delegate = self;
    picker.allowsMultipleSelection = NO;
    UIViewController *presenter = [self topViewController];
    if (presenter == nil) {
        [self finishWithPath:nil error:@"No active iOS view controller." cancelled:NO];
        return;
    }
    [presenter presentViewController:picker animated:YES completion:nil];
}

- (void)documentPicker:(UIDocumentPickerViewController *)controller
 didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    NSURL *source = urls.firstObject;
    if (source == nil) {
        [self finishWithPath:nil error:@"No document was selected." cancelled:NO];
        return;
    }

    NSString *filename = [NSString stringWithFormat:@"amod-import-%@.amod",
                           NSUUID.UUID.UUIDString];
    NSURL *target = [NSURL fileURLWithPath:
        [NSTemporaryDirectory() stringByAppendingPathComponent:filename]];
    NSError *error = nil;
    if (![[NSFileManager defaultManager] copyItemAtURL:source toURL:target error:&error]) {
        [self finishWithPath:nil
                       error:error.localizedDescription ?: @"The selected document could not be copied."
                   cancelled:NO];
        return;
    }
    [self finishWithPath:target.path error:nil cancelled:NO];
}

- (void)documentPicker:(UIDocumentPickerViewController *)controller
 didPickDocumentAtURL:(NSURL *)url {
    [self documentPicker:controller didPickDocumentsAtURLs:@[url]];
}

- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {
    [self finishWithPath:nil error:nil cancelled:YES];
}

- (void)finishWithPath:(NSString *)path
                 error:(NSString *)error
             cancelled:(BOOL)cancelled {
    id<RenpyFilePickerDelegate> delegate = self.delegate;
    self.delegate = nil;
    if (delegate != nil) {
        [delegate filePicker:self
          didFinishWithPath:path
                       error:error
                   cancelled:cancelled];
    }
}

- (UIViewController *)topViewController {
    UIWindow *window = nil;
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:[UIWindowScene class]]) {
            continue;
        }
        for (UIWindow *candidate in ((UIWindowScene *)scene).windows) {
            if (candidate.isKeyWindow) {
                window = candidate;
                break;
            }
        }
        if (window != nil) {
            break;
        }
    }
    UIViewController *controller = window.rootViewController;
    while (controller.presentedViewController != nil) {
        controller = controller.presentedViewController;
    }
    return controller;
}

@end
