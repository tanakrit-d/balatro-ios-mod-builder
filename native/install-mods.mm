// Added by balatro-ios-mod-builder. Called before LuaJIT initializes Lovely.
static void builder_install_mods_at_paths(NSString *bundle, NSString *documents)
{
    @autoreleasepool {
        NSFileManager *fm = [NSFileManager defaultManager];
        NSData *data = [NSData dataWithContentsOfFile:[bundle stringByAppendingPathComponent:@"bundled-mods.json"]];
        NSDictionary *current = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![current isKindOfClass:[NSDictionary class]]) {
            NSLog(@"Missing bundled mod manifest"); abort();
        }
        NSString *mods = [documents stringByAppendingPathComponent:@"game/Mods"];
        NSString *state = [documents stringByAppendingPathComponent:@"game/.builder-mods.json"];
        NSData *oldData = [NSData dataWithContentsOfFile:state];
        NSDictionary *previous = oldData ? [NSJSONSerialization JSONObjectWithData:oldData options:0 error:nil] : @{};
        if (![previous isKindOfClass:[NSDictionary class]]) { NSLog(@"Invalid mod state"); abort(); }
        NSError *error = nil;
        // Validate both manifests before changing anything in Documents.
        for (NSDictionary *manifest in @[current, previous]) {
            for (NSString *relative in manifest) {
                if ([relative hasPrefix:@"/"] || [[relative pathComponents] containsObject:@".."] || [[relative pathComponents] count] < 2) abort();
            }
        }
        if (![fm createDirectoryAtPath:mods withIntermediateDirectories:YES attributes:nil error:&error]) { NSLog(@"Cannot create mod directory: %@", error); abort(); }
        // Remove obsolete managed files first so paths can change type on upgrade.
        for (NSString *relative in previous) {
            if (current[relative]) continue;
            NSString *target = [mods stringByAppendingPathComponent:relative];
            BOOL directory = NO;
            if ([fm fileExistsAtPath:target isDirectory:&directory] && !directory && ![fm removeItemAtPath:target error:&error]) { NSLog(@"Cannot remove stale mod: %@", error); abort(); }
            NSString *parent = [target stringByDeletingLastPathComponent];
            while (![parent isEqualToString:mods]) {
                NSArray *children = [fm contentsOfDirectoryAtPath:parent error:&error];
                // Never remove a directory containing files created by the user or mods.
                if (!children || children.count) break;
                if (![fm removeItemAtPath:parent error:&error]) { NSLog(@"Cannot remove empty mod directory: %@", error); abort(); }
                parent = [parent stringByDeletingLastPathComponent];
            }
        }
        for (NSString *relative in current) {
            NSString *target = [mods stringByAppendingPathComponent:relative];
            // Configs and files created by mods are outside this ownership manifest.
            if ([current[relative] isEqual:previous[relative]] && [fm fileExistsAtPath:target]) continue;
            NSData *contents = [NSData dataWithContentsOfFile:[[bundle stringByAppendingPathComponent:@"bundled-mods"] stringByAppendingPathComponent:relative]];
            if (!contents || ![fm createDirectoryAtPath:[target stringByDeletingLastPathComponent] withIntermediateDirectories:YES attributes:nil error:&error] || ![contents writeToFile:target options:NSDataWritingAtomic error:&error]) {
                NSLog(@"Cannot install mod %@: %@", relative, error); abort();
            }
        }
        if (![data writeToFile:state options:NSDataWritingAtomic error:&error]) { NSLog(@"Cannot save mod state: %@", error); abort(); }
    }
}

extern "C" void builder_install_mods()
{
    builder_install_mods_at_paths([[NSBundle mainBundle] resourcePath], NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES)[0]);
}
