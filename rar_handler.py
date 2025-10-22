from PyQt5.QtWidgets import QFileDialog
import struct
# De momento descartado
def read_rar(file_path):
    with open(file_path, "rb") as file:
        data = file.read()
        # Leer los primeros bytes (por ejemplo, 7 para la firma RAR)
        header = data[:7]
        print(f"Header: {header}")
        
        # Extraer un bloque de datos, por ejemplo:
        signature = struct.unpack("<4s", data[:4])  # Leer 4 bytes como cadena
        print(f"Signature: {signature}")

def write_rar_header(output_file):
    with open(output_file, "wb") as file:
        # Escribir un encabezado ficticio (esto NO es realista para .rar)
        file.write(b"RAR!")  # Firma del archivo RAR
        file.write(struct.pack("<H", 0x0001))  # Versión ficticia
        print("Encabezado RAR escrito.")

def lzss_compress(input_data):
    compressed_data = []
    window = []
    
    for byte in input_data:
        if byte in window:
            # Generar un puntero al bloque existente
            index = window.index(byte)
            compressed_data.append((index, len(byte)))
        else:
            # Agregar byte literal
            compressed_data.append(byte)
        window.append(byte)
        if len(window) > 4096:  # Limitar el tamaño de la ventana
            window.pop(0)
    return compressed_data
