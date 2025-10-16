import re
import logging
from typing import List, Optional, Dict, Any
from difflib import SequenceMatcher

from utils.database import DatabaseConnection

logger = logging.getLogger(__name__)

class NameMatcher:
    """Name matching utilities"""
    
    @staticmethod
    def normalize_name(name: str) -> str:
        name = (name or "").lower().strip()
        name = re.sub(r'[^\w\s]', '', name)
        name = re.sub(r'\s+', ' ', name)
        return name

    @staticmethod
    def similarity_score(name1: str, name2: str) -> float:
        name1_norm = NameMatcher.normalize_name(name1)
        name2_norm = NameMatcher.normalize_name(name2)
        return SequenceMatcher(None, name1_norm, name2_norm).ratio()

class EmployeeService:
    """Service layer for employee operations"""
    
    def __init__(self):
        self.name_matcher = NameMatcher()
    
    def fetch_employees(self, search_term: str = None, emp_id: int = None) -> List[dict]:
        """Fetch employees from database"""
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            if emp_id:
                cursor.execute("""
                    SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                           d.status, d.doj, d.emp_number, d.blood_group,
                           u.username, d.opening_leave_balance
                    FROM developer d
                    LEFT JOIN user u ON d.user_id = u.user_id
                    WHERE d.id = %s
                """, (emp_id,))
            elif search_term:
                cursor.execute("""
                    SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                           d.status, d.doj, d.emp_number, d.blood_group,
                           u.username, d.opening_leave_balance
                    FROM developer d
                    LEFT JOIN user u ON d.user_id = u.user_id
                    WHERE d.developer_name LIKE %s OR d.email_id LIKE %s 
                       OR d.mobile LIKE %s OR d.emp_number LIKE %s
                    ORDER BY d.developer_name
                """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"))
            else:
                return []

            return cursor.fetchall()

        except Exception as e:
            logger.error(f"Database error in fetch_employees: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
    
    def get_leave_balance(self, employee_id: int) -> dict:
        """Calculate leave balance for an employee"""
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT opening_leave_balance
                FROM developer 
                WHERE id = %s
            """, (employee_id,))
            developer_info = cursor.fetchone()
            
            if not developer_info:
                raise ValueError("Employee not found")
            
            cursor.execute("""
                SELECT leave_type, COUNT(*) as count
                FROM leave_requests 
                WHERE developer_id = %s AND status = 'Approved'
                GROUP BY leave_type
            """, (employee_id,))
            leave_counts = cursor.fetchall()
            
            used_leaves = 0.0
            leave_details = {}
            
            for leave in leave_counts:
                lt = (leave.get('leave_type') or '').upper()
                cnt = float(leave.get('count') or 0)
                leave_details[lt] = int(cnt)
                
                if lt == 'FULL DAY':
                    used_leaves += cnt
                elif lt in ['HALF DAY', 'COMPENSATION HALF DAY']:
                    used_leaves += cnt * 0.5
                elif lt in ['2 HRS', 'COMPENSATION 2 HRS']:
                    used_leaves += cnt * 0.25
                else:
                    used_leaves += cnt

            opening_balance = float(developer_info.get('opening_leave_balance') or 0)
            current_balance = opening_balance - used_leaves
            
            return {
                "opening_balance": opening_balance,
                "used_leaves": used_leaves,
                "current_balance": current_balance,
                "leave_details": leave_details
            }
            
        except Exception as e:
            logger.error(f"Error calculating leave balance: {e}")
            raise
        finally:
            cursor.close()
            conn.close()