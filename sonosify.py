import argparse
import multiprocessing
import mutagen
import os
import shutil
import sys

MAX_MESSAGE = 76

def ClearLine() -> None:
    sys.stdout.write('\b'*MAX_MESSAGE)
    sys.stdout.write(' '*MAX_MESSAGE)
    sys.stdout.write('\b'*MAX_MESSAGE)
    sys.stdout.flush()

def PrintMessage(Message: str) -> None:
    '''
    Because of the updating logging, we need to handle this a little more delicately
    '''
    ClearLine()
    print(Message)

def ComputeDest(Path: str, DestRoot: str) -> str:
    '''
    Map a source file to its destination path using the last two directory
    components (artist/album) plus the filename.
    '''
    pathParts = Path.split(os.sep)
    return os.path.join(DestRoot, pathParts[-3], pathParts[-2], os.path.basename(Path))

def HandlePath(Path: str, DestRoot: str):
    '''
    Sync a single source file into the destination tree.

    Returns a (status, action) tuple:
      status - 'new'     destination did not exist and was created
               'updated' destination existed but was stale and was rebuilt
               'skipped' destination already up to date (source mtime unchanged)
               None      file could not be processed (not a regular file / unreadable)
      action - 'link'    destination was hard-linked from the source
               'copy'    destination was copied and retagged
               None      nothing was written
    '''
    if not os.path.isfile(Path):
        return (None, None)

    dest = ComputeDest(Path, DestRoot)
    srcStat = os.stat(Path)

    #
    # Decide whether anything needs to happen. Every destination we create is
    # stamped with the source mtime (hard links share it automatically, copies
    # get it restored after tag rewriting), so an unchanged mtime means the
    # destination is already current and can be skipped.
    #
    if os.path.isfile(dest):
        if os.stat(dest).st_mtime_ns == srcStat.st_mtime_ns:
            return ('skipped', None)
        os.remove(dest)
        status = 'updated'
    else:
        status = 'new'

    try:
        file = mutagen.File(Path, easy=True)
    except mutagen.mp4.MP4StreamInfoError:
        return (None, None)
    tags = file.tags

    dirname = os.path.dirname(dest)
    os.makedirs(dirname, exist_ok=True)

    isCompilation = 'Compilations' in Path.split(os.sep)

    #
    # If there is no albumartist or it is the same
    # as the artist, we can simply hard link
    #
    if isCompilation:
        shutil.copy2(Path, dest)
        m = mutagen.File(dest, easy=True)
        m['title'][0] = m['title'][0] + ' [' + m['artist'][0] + ']'
        m['artist'][0] = 'Compilation'
        m.save()
        os.utime(dest, ns=(srcStat.st_atime_ns, srcStat.st_mtime_ns))
        action = 'copy'
    elif 'albumartist' not in tags or tags['albumartist'] == tags['artist']:
        os.link(Path, dest)
        action = 'link'
    else:
        shutil.copy2(Path, dest)
        m = mutagen.File(dest, easy=True)
        if 'albumartist' in tags:
            assert(len(m['title']) == 1)
            assert(len(m['artist']) == 1)
            m['title'][0] = m['title'][0] + ' [' + m['artist'][0] + ']'
            m['artist'] = m['albumartist']
        m.save()
        os.utime(dest, ns=(srcStat.st_atime_ns, srcStat.st_mtime_ns))
        action = 'copy'

    return (status, action)

def Worker(Args):
    '''
    Pool worker: process a single file and capture any error so it can be
    reported by the parent instead of crashing the pool.

    Returns (path, status, action, error) where error is None on success or a
    message string on failure.
    '''
    Path, DestRoot = Args
    try:
        status, action = HandlePath(Path, DestRoot)
        return (Path, status, action, None)
    except Exception as e:
        message = e.message if hasattr(e, 'message') else str(e)
        return (Path, None, None, message)

def RemoveOrphans(DestRoot: str, Expected: set) -> int:
    '''
    Delete destination files that no longer correspond to a source file, then
    prune any directories left empty as a result. Returns the number of files
    removed.
    '''
    removed = 0
    if not os.path.isdir(DestRoot):
        return removed

    for root, dirs, files in os.walk(DestRoot):
        for filename in files:
            path = os.path.join(root, filename)
            if os.path.abspath(path) not in Expected:
                os.remove(path)
                removed += 1

    for root, dirs, files in os.walk(DestRoot, topdown=False):
        if os.path.abspath(root) == os.path.abspath(DestRoot):
            continue
        try:
            os.rmdir(root)
        except OSError:
            pass

    return removed

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Sonos Media Library Generator')
    parser.add_argument('source', type=str, help='Music Library Source Directory')
    parser.add_argument('destination', type=str, help='Destination Directory')
    parser.add_argument('--filter', type=str, default='m4a', help='Filetype filer')
    parser.add_argument('--jobs', '-j', type=int, default=os.cpu_count() or 1,
                        help='Number of worker processes (default: number of CPU cores)')
    args = parser.parse_args()

    filter = args.filter.split(',')

    new = 0
    updated = 0
    skipped = 0
    links = 0
    errors = 0
    expected = set()

    #
    # Gather the work first so it can be distributed across the pool. We also
    # build the set of expected destinations here so orphans can be pruned
    # afterwards.
    #
    tasks = []
    for root,dirs,files in os.walk(args.source):
        for filename in files:
            if filename.split('.')[-1] not in filter:
                continue
            path = os.path.join(root, filename)
            expected.add(os.path.abspath(ComputeDest(path, args.destination)))
            tasks.append((path, args.destination))

    jobs = max(1, args.jobs)
    pool = multiprocessing.Pool(processes=jobs)
    try:
        for path, status, action, error in pool.imap_unordered(Worker, tasks):
            ClearLine()
            if error is not None:
                errors += 1
                PrintMessage(f'[!] Error processing {os.path.basename(path)}: {error}')
            elif status == 'new':
                new += 1
            elif status == 'updated':
                updated += 1
            elif status == 'skipped':
                skipped += 1
            if action == 'link':
                links += 1

            sys.stdout.write('[N:{:05d} U:{:04d} S:{:05d} L:{:05d} E:{:03d}] {:34s}'.format(
                new,
                updated,
                skipped,
                links,
                errors,
                os.path.basename(path)[:34]
            ))
            sys.stdout.flush()
    except KeyboardInterrupt:
        pool.terminate()
        pool.join()
        sys.exit(3)
    else:
        pool.close()
        pool.join()

    ClearLine()
    deleted = RemoveOrphans(args.destination, expected)

    print(f'[+] New:     {new}')
    print(f'[+] Updated: {updated}')
    print(f'[+] Skipped: {skipped}')
    print(f'[+] Deleted: {deleted}')
    print(f'[+] Links:   {links}')
    print(f'[+] Errors:  {errors}')