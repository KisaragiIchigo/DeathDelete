from cryptography.fernet import Fernet

# キーを生成
key = Fernet.generate_key()

# ファイル化
with open("secret.key", "wb") as key_file:
    key_file.write(key)

print("暗号化キー 'secret.key' を生成しました。このファイルは大切に保管してください。")