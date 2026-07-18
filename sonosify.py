import argparse
import concurrent.futures
import mutagen
import os
import shutil
import sys

LINKS = 0
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

    Returns one of:
      'skipped' - destination already up to date (source mtime unchanged)
      'new'     - destination did not exist and was created
      'updated' - destination existed but was stale and was rebuilt
      None      - file could not be processed (not a regular file / unreadable)
    '''
    global LINKS

    if not os.path.isfile(Path):
        return None

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
            return 'skipped'
        os.remove(dest)
        status = 'updated'
    else:
        status = 'new'

    try:
        file = mutagen.File(Path, easy=True)
    except mutagen.mp4.MP4StreamInfoError:
        return None
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
    elif 'albumartist' not in tags or tags['albumartist'] == tags['artist']:
        os.link(Path, dest)
        LINKS += 1
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

    return status

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
    args = parser.parse_args()

    filter = args.filter.split(',')

    new = 0
    updated = 0
    skipped = 0
    errors = 0
    expected = set()

    for root,dirs,files in os.walk(args.source):
        for filename in files:
            if filename.split('.')[-1] not in filter:
                continue

            sys.stdout.write('[N:{:05d} U:{:04d} S:{:05d} L:{:05d} E:{:03d}] {:34s}'.format(
                new,
                updated,
                skipped,
                LINKS,
                errors,
                filename[:34]
            ))
            sys.stdout.flush()
            path = os.path.join(root, filename)
            expected.add(os.path.abspath(ComputeDest(path, args.destination)))
            try:
                status = HandlePath(path, args.destination)
                if status == 'new':
                    new += 1
                elif status == 'updated':
                    updated += 1
                elif status == 'skipped':
                    skipped += 1
            except KeyboardInterrupt:
                sys.exit(3)
            except Exception as e:
                errors += 1
                if hasattr(e, 'message'):
                    PrintMessage(f'[!] Error processing {filename}: {e.message}')
                else:
                    PrintMessage(f'[!] Error processing {filename}: {str(e)}')
                continue
            ClearLine()

    ClearLine()
    deleted = RemoveOrphans(args.destination, expected)

    print(f'[+] New:     {new}')
    print(f'[+] Updated: {updated}')
    print(f'[+] Skipped: {skipped}')
    print(f'[+] Deleted: {deleted}')
    print(f'[+] Links:   {LINKS}')
    print(f'[+] Errors:  {errors}')