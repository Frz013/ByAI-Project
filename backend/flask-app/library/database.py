from .operasi import create_first_data

DB_FILE = "data.txt"
TEMPLATE = {
    "pk" : "XXXXXX",
    "date_add" : "DD-MM_YYYY",
    "judul" : " "*90,
    "penulis" : " "*90,
    "tahun" : "YYYY",
}
def init_console():

    try:
        with open(DB_FILE,"r") as file:
            print("Database tersedia")
            isi = file.read()

    except:
        print("Database tidak tersedia, silahkan buat data baru: ")
        create_first_data()

            
