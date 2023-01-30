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

def HandlePath(Path: str, DestRoot: str) -> bool:
    global LINKS
    if not os.path.isfile(Path):
        return False
    isCompilation = 'Compilations' in Path.split(os.sep)
    try:
        file = mutagen.File(Path, easy=True)
    except mutagen.mp4.MP4StreamInfoError:
        return False
    tags = file.tags
    
    pathParts = Path.split(os.sep)

    dest = os.path.join(DestRoot, pathParts[-3], pathParts[-2], os.path.basename(Path))
    dirname = os.path.dirname(dest)
    os.makedirs(dirname, exist_ok=True)

    if os.path.isfile(dest):
        print('[i] Skipping duplicate file')
        return False

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

    return True

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Sonos Media Library Generator')
    parser.add_argument('source', type=str, help='Music Library Source Directory')
    parser.add_argument('destination', type=str, help='Destination Directory')
    parser.add_argument('--filter', type=str, default='m4a', help='Filetype filer')
    args = parser.parse_args()

    if os.path.isdir(args.destination):
        print('[!] ERROR: Destination exists')
        sys.exit(1)

    filter = args.filter.split(',')

    count = 0
    errors = 0

    for root,dirs,files in os.walk(args.source):
        for filename in files:
            if filename.split('.')[-1] not in filter:
                continue
            
            # sys.stdout.write(f'[#:{count} L:{LINKS} C:{count-LINKS} E:{errors}] {filename[:30]}')
            sys.stdout.write('[#:{:05d} L:{:05d} C:{:05d} E:{:03d}] {:40s}'.format(
                count,
                LINKS,
                count-LINKS,
                errors,
                filename[:40]
            ))
            sys.stdout.flush()
            path = os.path.join(root, filename)
            try:
                if HandlePath(path, args.destination):
                    count += 1
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

    print(f'[+] Total: {count}')
    print(f'[+] Links: {LINKS}')