#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

@protocol RenpyFilePickerDelegate <NSObject>
- (void)filePicker:(id)picker
 didFinishWithPath:(nullable NSString *)path
             error:(nullable NSString *)error
         cancelled:(BOOL)cancelled;
@end

@interface RenpyFilePicker : NSObject <UIDocumentPickerDelegate>
- (void)openAmodPickerWithDelegate:(id<RenpyFilePickerDelegate>)delegate
                temporaryDirectory:(NSString *)temporaryDirectory;
@end

NS_ASSUME_NONNULL_END
