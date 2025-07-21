import argparse
import json
import os
import sys

import psycopg2


def get_db_connection():
    host = os.environ.get("DB_HOST", "")
    database = os.environ.get("DB_NAME", "")
    user = os.environ.get("DB_USER", "")
    password = os.environ.get("DB_PASSWORD", "")
    
    try:
        conn = psycopg2.connect(
            host=host,
            database=database,
            user=user,
            password=password
        )
        return conn
    except Exception as e:
        sys.stderr.write(f"Error connecting to database: {e}\n")
        sys.exit(1)

def log_datasets_initial(datasets, workflow_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for dataset in datasets:
            cursor.execute(
                """
                INSERT INTO automate_metashape (dataset_name, workflow_id, status) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (dataset_name, workflow_id) DO NOTHING
                """,
                (dataset, workflow_id, 'queued')
            )
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"Error logging to database: {e}\n")
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()

def log_dataset_start(dataset, workflow_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE automate_metashape 
            SET status = 'processing', start_time = CURRENT_TIMESTAMP 
            WHERE dataset_name = %s AND workflow_id = %s
            """,
            (dataset, workflow_id)
        )
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"Error logging start time: {e}\n")
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()

def log_dataset_completion(dataset, workflow_id, success):
    conn = get_db_connection()
    status = 'completed' if success else 'failed'
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE automate_metashape 
            SET status = %s, finish_time = CURRENT_TIMESTAMP 
            WHERE dataset_name = %s AND workflow_id = %s
            """,
            (status, dataset, workflow_id)
        )
        conn.commit()
    except Exception as e:
        sys.stderr.write(f"Error logging completion: {e}\n")
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()

def main():
    parser = argparse.ArgumentParser(description='Database logging for Argo workflows')
    
    parser.add_argument('action', choices=['log-initial', 'log-start', 'log-completion'],
                      help='Logging action to perform')
    
    parser.add_argument('--workflow-id', required=True,
                      help='Workflow ID to use in database records')
    
    parser.add_argument('--datasets-json',
                      help='JSON array of dataset names for initial logging')
    parser.add_argument('--dataset',
                      help='Dataset name for start/completion logging')
    parser.add_argument('--success',
                      help='Success status (true/false) for completion logging')
    
    args = parser.parse_args()
    
    if args.action == 'log-initial':
        if not args.datasets_json:
            sys.stderr.write("Error: --datasets-json is required for log-initial action\n")
            sys.exit(1)
        datasets = json.loads(args.datasets_json)
        log_datasets_initial(datasets, args.workflow_id)
    
    elif args.action == 'log-start':
        if not args.dataset:
            sys.stderr.write("Error: --dataset is required for log-start action\n")
            sys.exit(1)
        log_dataset_start(args.dataset, args.workflow_id)
    
    elif args.action == 'log-completion':
        if not args.dataset or args.success is None:
            sys.stderr.write("Error: --dataset and --success are required for log-completion action\n")
            sys.exit(1)
        success = args.success.lower() == 'true'
        log_dataset_completion(args.dataset, args.workflow_id, success)

if __name__ == "__main__":
    main()