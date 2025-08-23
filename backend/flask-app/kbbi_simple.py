"""
Simple KBBI implementation with hardcoded data for testing
"""

# Sample KBBI data untuk testing
KBBI_DATA = {
    "pijar": {
        "lema": ["pijar"],
        "definisi": [
            "[n] bara api; api yang menyala-nyala",
            "[a] berpijar; bersinar terang seperti api"
        ],
        "entri": [
            {
                "lema": "pijar",
                "makna": [
                    {
                        "kelas": "n",
                        "deskripsi": "bara api; api yang menyala-nyala",
                        "contoh": ["Pijar api unggun menerangi malam"],
                        "sinonim": ["bara", "api"],
                        "antonim": []
                    },
                    {
                        "kelas": "a", 
                        "deskripsi": "berpijar; bersinar terang seperti api",
                        "contoh": ["Matanya pijar penuh semangat"],
                        "sinonim": ["bersinar", "berkilau"],
                        "antonim": ["redup", "padam"]
                    }
                ]
            }
        ]
    },
    "rumah": {
        "lema": ["rumah"],
        "definisi": [
            "[n] bangunan untuk tempat tinggal",
            "[n] bangunan pada umumnya (seperti toko, kantor, sekolah)"
        ],
        "entri": [
            {
                "lema": "rumah",
                "makna": [
                    {
                        "kelas": "n",
                        "deskripsi": "bangunan untuk tempat tinggal",
                        "contoh": ["Rumah kami terletak di ujung jalan"],
                        "sinonim": ["hunian", "tempat tinggal"],
                        "antonim": []
                    }
                ]
            }
        ]
    },
    "buku": {
        "lema": ["buku"],
        "definisi": [
            "[n] lembar kertas yang berjilid, berisi tulisan atau kosong"
        ],
        "entri": [
            {
                "lema": "buku",
                "makna": [
                    {
                        "kelas": "n",
                        "deskripsi": "lembar kertas yang berjilid, berisi tulisan atau kosong",
                        "contoh": ["Buku ini sangat menarik untuk dibaca"],
                        "sinonim": ["kitab"],
                        "antonim": []
                    }
                ]
            }
        ]
    }
}

def normalize_kata(kata):
    """Normalize kata untuk pencarian"""
    return kata.lower().strip()

def cari_kata(kata):
    """Cari kata dalam data KBBI sederhana"""
    kata_norm = normalize_kata(kata)
    return KBBI_DATA.get(kata_norm)

def get_saran(kata):
    """Berikan saran kata berdasarkan prefix"""
    kata_norm = normalize_kata(kata)
    saran = []
    for k in KBBI_DATA.keys():
        if k.startswith(kata_norm[:2]):
            saran.append(k)
    return sorted(saran)[:5]
