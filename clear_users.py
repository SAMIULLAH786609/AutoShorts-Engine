from sqlalchemy import create_engine, text

url = 'postgresql://postgres.qhyevwvywndsoepvkajq:%40utoShorts123@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres'

try:
    print('Connecting to database...')
    engine = create_engine(url, connect_args={'sslmode': 'require'})
    with engine.connect() as conn:
        print('Deleting old test users...')
        conn.execute(
            text("DELETE FROM users WHERE email IN ('samiullahmuhammad076@gmail.com', '786muhammad.samiullah@gmail.com', 'cloudtest4@autoshorts.app')")
        )
        conn.commit()
        print('Users successfully deleted from database!')
except Exception as e:
    print('Error:', e)
