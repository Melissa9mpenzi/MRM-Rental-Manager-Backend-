# Import ALL models here — Alembic needs to see them all for autogenerate
from app.models.user import User
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.lease import Lease, LeaseStatus
from app.models.payment import Payment, PaymentMethod, PaymentType
from app.models.payment_checkout import PaymentCheckout, CheckoutStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.maintenance import MaintenanceRequest
from app.models.notification import Notification, NotifType
from app.models.audit import AuditLog
from app.models.saved_unit import SavedUnit
from app.models.conversation import MessageThread, ThreadParticipant, Message