import re
import logging
from typing import List, Optional, Dict, Any
from difflib import SequenceMatcher


from utils.database import DatabaseConnection
from models.employee import Employee, LeaveBalance

logger = logging.getLogger(__name__)

class NameMatcher:
    """AI-powered name matching utilities"""
    
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

        if Levenshtein:
            try:
                dist = Levenshtein.distance(name1_norm, name2_norm)
                levenshtein_sim = 1 - (dist / max(len(name1_norm), len(name2_norm), 1))
            except Exception:
                levenshtein_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        else:
            levenshtein_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()

        sequence_sim = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        combined_score = (levenshtein_sim * 0.6) + (sequence_sim * 0.4)
        return combined_score

    @staticmethod
    def fuzzy_match_employee(search_name: str, employees: List[Employee], threshold: float = 0.6) -> List[Dict[str, Any]]:
        matches = []
        
        for emp in employees:
            scores = []
            emp_full_name = emp.developer_name.strip()
            scores.append(NameMatcher.similarity_score(search_name, emp_full_name))

            best_score = max(scores) if scores else 0
            if best_score >= threshold:
                matches.append({'employee': emp, 'score': best_score, 'match_type': 'fuzzy'})

        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches

class EmployeeService:
    """Service layer for employee operations"""
    
    def __init__(self):
        self.name_matcher = NameMatcher()
    
    def fetch_employees(self, search_term: str = None, emp_id: int = None) -> List[Employee]:
        """Fetch employees from database"""
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            if emp_id:
                cursor.execute("""
                    SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                           d.status, d.doj, d.emp_number, d.blood_group,
                           u.username, d.opening_leave_balance, d.is_pf_enabled, d.pf_join_date
                    FROM developer d
                    LEFT JOIN user u ON d.user_id = u.user_id
                    WHERE d.id = %s
                """, (emp_id,))
            elif search_term:
                cursor.execute("""
                    SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                           d.status, d.doj, d.emp_number, d.blood_group,
                           u.username, d.opening_leave_balance, d.is_pf_enabled, d.pf_join_date
                    FROM developer d
                    LEFT JOIN user u ON d.user_id = u.user_id
                    WHERE d.developer_name LIKE %s OR d.email_id LIKE %s 
                       OR d.mobile LIKE %s OR d.emp_number LIKE %s
                    ORDER BY d.developer_name
                """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"))
            else:
                return []

            rows = cursor.fetchall()
            employees = [Employee.from_dict(row) for row in rows]

            # Fallback to fuzzy search if no exact matches found
            if search_term and not employees:
                employees = self._fuzzy_search_fallback(search_term)

            return employees

        except Exception as e:
            logger.error(f"Database error in fetch_employees: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
    
    def _fuzzy_search_fallback(self, search_term: str) -> List[Employee]:
        """Fallback to fuzzy search among active employees"""
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT d.id, d.developer_name, d.designation, d.email_id, d.mobile, 
                       d.status, d.doj, d.emp_number, d.blood_group,
                       u.username, d.opening_leave_balance, d.is_pf_enabled, d.pf_join_date
                FROM developer d
                LEFT JOIN user u ON d.user_id = u.user_id
                WHERE d.status = 1
            """)
            all_employees_data = cursor.fetchall()
            all_employees = [Employee.from_dict(emp) for emp in all_employees_data]
            
            fuzzy_matches = self.name_matcher.fuzzy_match_employee(search_term, all_employees)
            return [match['employee'] for match in fuzzy_matches[:5]]
            
        except Exception as e:
            logger.error(f"Error in fuzzy search fallback: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
    
    def get_leave_balance(self, employee_id: int) -> LeaveBalance:
        """Calculate leave balance for an employee"""
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT opening_leave_balance, doj, status 
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
            
            return LeaveBalance(
                opening_balance=opening_balance,
                used_leaves=used_leaves,
                current_balance=current_balance,
                leave_details=leave_details
            )
            
        except Exception as e:
            logger.error(f"Error calculating leave balance: {e}")
            raise
        finally:
            cursor.close()
            conn.close()