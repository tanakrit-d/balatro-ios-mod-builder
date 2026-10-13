// Added by balatro-ios-mod-builder. Called before LuaJIT initializes Lovely.
extern "C" void builder_install_mods()
{
    @autoreleasepool {
        NSFileManager *fm = [NSFileManager defaultManager];
        NSString *bundle = [[NSBundle mainBundle] resourcePath];
        NSData *data = [NSData dataWithContentsOfFile:[bundle stringByAppendingPathComponent:@"bundled-mods.json"]];
        NSDictionary *current = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![current isKindOfClass:[NSDictionary class]]) {
            NSLog(@"Missing bundled mod manifest"); abort();
        }
        NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES)[0];
        NSString *mods = [documents stringByAppendingPathComponent:@"game/Mods"];
        NSString *state = [documents stringByAppendingPathComponent:@"game/.builder-mods.json"];
        NSData *oldData = [NSData dataWithContentsOfFile:state];
        NSDictionary *previous = oldData ? [NSJSONSerialization JSONObjectWithData:oldData options:0 error:nil] : @{};
        if (![previous isKindOfClass:[NSDictionary class]]) { NSLog(@"Invalid mod state"); abort(); }
        NSError *error = nil;
        for (NSString *relative in current) {
            if ([relative hasPrefix:@"/"] || [[relative pathComponents] containsObject:@".."] || [[relative pathComponents] count] < 2) abort();
            NSString *target = [mods stringByAppendingPathComponent:relative];
            // Configs and files created by mods are outside this ownership manifest.
            if ([current[relative] isEqual:previous[relative]] && [fm fileExistsAtPath:target]) continue;
            NSData *contents = [NSData dataWithContentsOfFile:[[bundle stringByAppendingPathComponent:@"bundled-mods"] stringByAppendingPathComponent:relative]];
            if (!contents || ![fm createDirectoryAtPath:[target stringByDeletingLastPathComponent] withIntermediateDirectories:YES attributes:nil error:&error] || ![contents writeToFile:target options:NSDataWritingAtomic error:&error]) {
                NSLog(@"Cannot install mod %@: %@", relative, error); abort();
            }
        }
        for (NSString *relative in previous) {
            if ([relative hasPrefix:@"/"] || [[relative pathComponents] containsObject:@".."] || [[relative pathComponents] count] < 2) abort();
            NSString *target = [mods stringByAppendingPathComponent:relative];
            if (!current[relative] && [fm fileExistsAtPath:target] && ![fm removeItemAtPath:target error:&error]) { NSLog(@"Cannot remove stale mod: %@", error); abort(); }
        }
        if (![data writeToFile:state options:NSDataWritingAtomic error:&error]) { NSLog(@"Cannot save mod state: %@", error); abort(); }
    }
}
