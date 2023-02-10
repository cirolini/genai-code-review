# Open File and print lines
def openFile():
    f = open('test.txt', 'r')
    for line in f:
        print line
    f.close()


# Main
if __name__ == '__main__':
    openFile()
