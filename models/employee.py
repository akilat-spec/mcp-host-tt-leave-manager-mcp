from typing import Optional, Dict, Any
from datetime import date, datetime
from dataclasses import dataclass

@dataclass
class Employee:
    """Employee data model"""
    id: int
    developer_name: str
    designation: Optional[str] = None
    email_id: Optional[str] = None
    mobile: Optional[str] = None
    status: int = 1
    doj: Optional[date] = None
    emp_number: Optional[str] = None
    blood_group: Optional[str] = None
    username: Optional[str] = None
    opening_leave_balance: float = 0.0
    is_pf_enabled: bool = False
    pf_join_date: Optional[date] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Employee':
        """Create Employee instance from database row"""
        return cls(
            id=data.get('id'),
            developer_name=data.get('developer_name', ''),
            designation=data.get('designation'),
            email_id=data.get('email_id'),
            mobile=data.get('mobile'),
            status=data.get('status', 1),
            doj=data.get('doj'),
            emp_number=data.get('emp_number'),
            blood_group=data.get('blood_group'),
            username=data.get('username'),
            opening_leave_balance=float(data.get('opening_leave_balance', 0)),
            is_pf_enabled=bool(data.get('is_pf_enabled', False)),
            pf_join_date=data.get('pf_join_date')
        )
    
    @property
    def is_active(self) -> bool:
        """Check if employee is active"""
        return self.status == 1

@dataclass
class LeaveBalance:
    """Leave balance information"""
    opening_balance: float = 0.0
    used_leaves: float = 0.0
    current_balance: float = 0.0
    leave_details: Dict[str, int] = None
    
    def __post_init__(self):
        if self.leave_details is None:
            self.leave_details = {}