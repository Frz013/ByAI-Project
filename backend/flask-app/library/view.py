from . import operasi
import os


def read_console():
    isi_data = operasi.read()
    index = "No"
    penulis = "Penulis"
    judul = "Judul"
    tahun = "tahun"

    #Header
    print("="*100 +"\n")
    print(f"{index:4} | {penulis:40} | {judul:40} | {tahun:5}")
    print("-"*100)

    #content
    for index,data in enumerate(isi_data):
        data_break = data.split(",")

        pk = data_break[0]
        date_add = data_break[1]
        penulis = data_break[2]
        judul = data_break[3]
        tahun = data_break[4]

        print(f"{index+1:4} | {penulis:.40} | {judul:.40} | {tahun:4}", end="")
    
    #Footer
    print("\n"+ "="*100)

def create_console():
    print("\n\n" + "="*100)
    print("Silahkan tambahkan data buku")

    penulis = input("Penulis:\t")
    judul = input("Judul:\t")
    while True:
        tahun = input("Tahun: \t")
        try:
            if len(str(tahun)) == 4:
                break
            else:
                print("Masukan 4 digit angka (YYYY)")
        except:
            print("Masukan 4 digit angka (YYYY)")

    sistem_operasi = os.name
    match sistem_operasi:
        case "posix": os.system("clear")
        case "nt": os.system("cls")

    operasi.create_data(penulis,judul,tahun)
    print("Data buku berhasil ditambahkan")
    read_console()


def update_console():
    read_console()

    nomor_buku = int(input("Pilih nomor buku yang ingin di update: "))

    operasi.read(index=nomor_buku)