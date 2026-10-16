import os
import re
import secrets
import hashlib
import smtplib
from email.message import EmailMessage
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, UniqueConstraint
from urllib.parse import quote_plus
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-change-this-secret-before-deployment')
app.config['ADMIN_EMAIL'] = os.getenv('ADMIN_EMAIL', '').strip().lower()
database_url = os.getenv('DATABASE_URL', '').strip()
# Render PostgreSQL URLs may use the legacy postgres:// scheme; SQLAlchemy expects postgresql://.
if database_url.startswith('postgres://'):
    database_url = 'postgresql://' + database_url[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or ('sqlite:///' + os.path.join(BASE_DIR, 'travel_buddy_finder.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
db = SQLAlchemy(app)
migrate = Migrate(app, db)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(100), default='')
    bio = db.Column(db.String(500), default='')
    interests = db.Column(db.String(300), default='')
    travel_style = db.Column(db.String(80), default='Flexible')
    budget = db.Column(db.Integer, default=15000)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def public(self):
        return {'id': self.id, 'name': self.name, 'email': self.email, 'city': self.city, 'bio': self.bio,
                'interests': [x.strip() for x in (self.interests or '').split(',') if x.strip()],
                'travel_style': self.travel_style, 'budget': self.budget}

class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    destination = db.Column(db.String(120), nullable=False, index=True)
    start_location = db.Column(db.String(120), default='')
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    budget = db.Column(db.Integer, default=0)
    description = db.Column(db.Text, default='')
    interests = db.Column(db.String(300), default='')
    max_members = db.Column(db.Integer, default=4)
    status = db.Column(db.String(20), default='open')
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User', backref='created_trips')

class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    trip = db.relationship('Trip', backref='memberships')
    user = db.relationship('User', backref='memberships')
    __table_args__ = (UniqueConstraint('trip_id', 'user_id', name='uq_trip_member'),)

class Connection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])
    __table_args__ = (UniqueConstraint('sender_id', 'receiver_id', name='uq_connection_pair'),)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    details = db.Column(db.String(400), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    trip = db.relationship('Trip', backref='expenses')
    user = db.relationship('User')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])

class VerificationRequest(db.Model):
    """Stores verification status only; never stores ID images or ID numbers."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    document_type = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', foreign_keys=[user_id])
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])

class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    quiz_key = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    points_awarded = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')
    __table_args__ = (UniqueConstraint('user_id', 'quiz_key', name='uq_user_quiz_attempt'),)

class CouponRedemption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    points_cost = db.Column(db.Integer, nullable=False, default=200)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')

class PasswordResetOTP(db.Model):
    """Short-lived password reset codes; only a hash of each OTP is stored."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship('User')

class ItineraryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    time = db.Column(db.String(20), default='')
    notes = db.Column(db.String(500), default='')
    cost = db.Column(db.Float, default=0)
    trip = db.relationship('Trip', backref='itinerary_items')
    user = db.relationship('User')


def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.path.startswith('/api/'):
                return jsonify(error='Please log in first.'), 401
            flash('Please log in to continue.', 'info')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def trip_access(trip_id, user=None):
    user = user or current_user()
    trip = db.session.get(Trip, trip_id)
    if not trip or not user:
        abort(404)
    is_member = trip.creator_id == user.id or Membership.query.filter_by(trip_id=trip.id, user_id=user.id, status='accepted').first()
    if not is_member:
        abort(403)
    return trip

def expense_totals(trip):
    categories = {'Accommodation': 0, 'Transportation': 0, 'Activities': 0, 'Food': 0, 'Other': 0}
    for exp in trip.expenses:
        categories[exp.category] = categories.get(exp.category, 0) + exp.amount
    return categories

def destination_image(destination, seed=0):
    """Return a safe destination photo URL and vary images for repeated trip cards.

    Known destinations use their mapped image on the first occurrence. If the same
    destination appears on multiple trip cards, a different image from the curated
    photo pool is selected using the trip ID. Unknown/alias destinations never raise
    KeyError; they fall back to a stable image from the same pool.
    """
    import hashlib
    value = (destination or '').strip().lower()
    place_images = PLACE_IMAGE_IDS
    aliases = {
        'andaman': 'Andaman and Nicobar Islands', 'andaman & nicobar': 'Andaman and Nicobar Islands',
        'uk': 'United Kingdom', 'usa': 'United States', 'us': 'United States',
        'turkey': 'Türkiye', 'turkiye': 'Türkiye',
        'goa, india': 'Goa', 'kerala, india': 'Kerala', 'ladakh, india': 'Ladakh',
        'jaipur, india': 'Jaipur', 'udaipur, india': 'Udaipur', 'rishikesh, india': 'Rishikesh',
        'darjeeling, india': 'Darjeeling', 'hampi, india': 'Hampi', 'varanasi, india': 'Varanasi',
        'sikkim, india': 'Sikkim', 'bali': 'Indonesia', 'bali, indonesia': 'Indonesia',
        'tokyo': 'Japan', 'kyoto': 'Japan', 'paris': 'France', 'rome': 'Italy', 'venice': 'Italy',
        'barcelona': 'Spain', 'madrid': 'Spain', 'zurich': 'Switzerland', 'interlaken': 'Switzerland',
        'bangkok': 'Thailand', 'phuket': 'Thailand', 'kathmandu': 'Nepal', 'pokhara': 'Nepal',
        'new york': 'United States', 'new york city': 'United States', 'london': 'United Kingdom',
        'cape town': 'South Africa', 'queenstown': 'New Zealand', 'sydney': 'Australia',
        'melbourne': 'Australia', 'male': 'Maldives', 'cairo': 'Egypt', 'agra': 'Jaipur',
        'jodhpur': 'Jaipur', 'manali': 'Ladakh', 'munnar': 'Kerala', 'coorg': 'Kerala',
        'pondicherry': 'Puducherry', 'pondicherry, india': 'Puducherry', 'puducherry, india': 'Puducherry',
        'mysore': 'Mysuru', 'rann of kutch': 'Kutch',
    }
    key = aliases.get(value)
    if key not in place_images:
        key = next((name for name in place_images if value == name.lower() or value.startswith(name.lower() + ',') or value.endswith(', ' + name.lower())), None)
    if key is None:
        key = next((name for name in place_images if name.lower() in value), None)

    # Keep the location's mapped photo when possible. For aliases/missing entries or
    # repeated trips to the same mapped destination, use a distinct photo ID from
    # the curated pool so Explore Trips does not reuse the same exact image URL.
    pool = list(dict.fromkeys(place_images.values()))
    if key is not None:
        preferred = place_images[key]
    else:
        preferred = None
    try:
        trip_seed = int(seed or 0)
    except (TypeError, ValueError):
        trip_seed = int(hashlib.sha256(str(seed).encode('utf-8')).hexdigest()[:8], 16)

    if preferred is not None and trip_seed == 0:
        image_id = preferred
    elif preferred is not None:
        # The seed rotates among unique destination images, avoiding identical photos
        # when multiple trip cards share a destination. Stable per trip across refreshes.
        preferred_index = pool.index(preferred)
        image_id = pool[(preferred_index + trip_seed) % len(pool)]
    else:
        index = int(hashlib.sha256(value.encode('utf-8')).hexdigest()[:8], 16)
        image_id = pool[(index + trip_seed) % len(pool)]
    return f'https://images.unsplash.com/{image_id}?auto=format&fit=crop&w=1200&q=85'

PLACE_IMAGE_IDS = {'Ladakh': 'photo-1500530855697-b586d89ba3ee', 'Kerala': 'photo-1602216056096-3b40cc0c9944', 'Jaipur': 'photo-1477587458883-47145ed94245', 'Goa': 'photo-1500375592092-40eb2168fd21', 'Rishikesh': 'photo-1500534623283-312aAde485b7', 'Darjeeling': 'photo-1519681393784-d120267933ba', 'Udaipur': 'photo-1514222134-b57cbb8ce073', 'Andaman and Nicobar Islands': 'photo-1507525428034-b723cf961d3e', 'Meghalaya': 'photo-1441974231531-c6227db76b6e', 'Hampi': 'photo-1606293926075-69a00dbfde81', 'Varanasi': 'photo-1561361513-2d000a50f0dc', 'Sikkim': 'photo-1464822759023-fed622ff2c3b', 'Japan': 'photo-1493976040374-85c8e12f0c0e', 'France': 'photo-1502602898657-3e91760cbb34', 'Switzerland': 'photo-1531366936337-7c912a4589a7', 'Italy': 'photo-1552832230-c0197dd311b5', 'Spain': 'photo-1539037116277-4db20889f2d4', 'Canada': 'photo-1503614472-8c93d56cdab4', 'Australia': 'photo-1506973035872-a4ec16b8e8d9', 'New Zealand': 'photo-1469521669194-babb45599def', 'Indonesia': 'photo-1537996194471-e657df975ab4', 'Thailand': 'photo-1508009603885-50cf7c579365', 'Nepal': 'photo-1544735716-392fe2489ffa', 'Singapore': 'photo-1525625293386-3f8f99389edd', 'Portugal': 'photo-1555881400-74d7acaacd8b', 'Türkiye': 'photo-1524231757912-21f4fe3a7200', 'United States': 'photo-1496442226666-8d4d0e62e6e9', 'South Africa': 'photo-1580060839134-75a5edca2e99', 'United Kingdom': 'photo-1513635269975-59663e0ac1ad', 'Maldives': 'photo-1514282401047-d79a71a590e8', 'Malaysia': 'photo-1596422846543-75c6fc197f07', 'Egypt': 'photo-1539768942893-daf53e448371', 'Greece': 'photo-1533105079780-92b9be482077', 'Morocco': 'photo-1489749798305-4fea3ae63d43', 'Vietnam': 'photo-1528127269322-539801943592', 'Philippines': 'photo-1518509562904-e7ef99cdcc86', 'Brazil': 'photo-1483729558449-99ef09a8c325', 'Mexico': 'photo-1512813195386-6cf811ad3542', 'Austria': 'photo-1516550893923-42d28e5677af', 'Netherlands': 'photo-1512470876302-972faa2aa9a4'}

def avatar_url(user):
    """Use a human portrait, never a destination image, for buddy cards.
    Demo names are mapped to gender-appropriate portrait sets; unknown names get a neutral avatar."""
    name = (getattr(user, 'name', '') or '').strip().split(' ')[0].lower()
    women = {'sana','riya','meera','ananya','zoya','tanya','naina','pooja'}
    men = {'aarav','kabir','dev','ishaan','arjun','vihaan','rehan','aditya'}
    female_ids = {'sana':44,'riya':47,'meera':49,'ananya':32,'zoya':68,'tanya':25,'naina':52,'pooja':56,'isha':65,'kavya':45,'maya':67,'elena':23,'aisha':29,'lucia':46,'yuna':24,'tara':57,'noor':39,'kiara':31,'priya':50,'chloe':33,'fatima':40}
    male_ids = {'aarav':12,'kabir':33,'dev':15,'ishaan':18,'arjun':14,'vihaan':22,'rehan':51,'aditya':59,'neel':61,'rohan':27,'mateo':34,'liam':42,'daniel':56,'kenji':62,'omar':36,'leo':17,'sam':44,'alex':48,'ethan':30,'amir':53}
    if name in women:
        ident = female_ids[name]
        return f'https://randomuser.me/api/portraits/women/{ident}.jpg'
    if name in men:
        ident = male_ids[name]
        return f'https://randomuser.me/api/portraits/men/{ident}.jpg'
    # For new accounts, use a neutral initials-style SVG data URI rather than guessing gender.
    initials = ((getattr(user, 'name', '') or 'T').strip()[:1] or 'T').upper()
    import urllib.parse
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='128' height='128'><rect width='128' height='128' rx='64' fill='%23dbe8dd'/><text x='64' y='82' font-size='54' text-anchor='middle' fill='%231e5954' font-family='Arial'>{initials}</text></svg>"
    return 'data:image/svg+xml,' + urllib.parse.quote(svg)



def alternate_domestic_international(trips):
    """Interleave Indian and international destinations while preserving relative order."""
    international_markers = ('japan','indonesia','france','portugal','switzerland','thailand','türkiye','turkiye','south africa','singapore','australia','usa','united states','italy','spain','netherlands','united kingdom','uk','uae','south korea','nepal','sri lanka','maldives','czech','austria','mexico','canada')
    domestic, international = [], []
    for trip in trips:
        dest = (trip.destination or '').lower()
        is_india = any(marker in dest for marker in ('india','ladakh','goa','kerala','jaipur','rishikesh','manali','udaipur','meghalaya','shillong','mumbai','andaman','varanasi','coorg','spiti','agra','pondicherry','puducherry','mysuru','darjeeling','hampi','sikkim','kutch','orchha','lakshadweep','ziro','jodhpur'))
        is_intl = False if is_india else (any(marker in dest for marker in international_markers) or ',' in dest)
        (international if is_intl else domestic).append(trip)
    mixed=[]
    for i in range(max(len(domestic),len(international))):
        if i < len(domestic): mixed.append(domestic[i])
        if i < len(international): mixed.append(international[i])
    return mixed

@app.context_processor
def inject_globals():
    return {'logged_user': current_user(), 'money': lambda value: f'₹{float(value or 0):,.0f}', 'destination_image': destination_image, 'avatar_url': avatar_url}

@app.route('/service-worker.js')
def service_worker():
    response = send_from_directory(os.path.join(BASE_DIR, 'static'), 'service-worker.js', mimetype='application/javascript')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/')
def home():
    trips = alternate_domestic_international(Trip.query.filter_by(status='open').order_by(Trip.created_at.desc()).all())[:9]
    return render_template('index.html', trips=trips)

def send_password_reset_email(recipient, code):
    """Send the reset OTP using SMTP settings supplied through environment variables."""
    host = os.getenv('SMTP_HOST', '').strip()
    username = os.getenv('SMTP_USERNAME', '').strip()
    password = os.getenv('SMTP_PASSWORD', '')
    sender = os.getenv('SMTP_FROM', username).strip()
    if not host or not sender:
        raise RuntimeError('Email delivery is not configured. Add SMTP settings to your .env file.')
    port = int(os.getenv('SMTP_PORT', '587'))
    use_tls = os.getenv('SMTP_USE_TLS', '1').strip().lower() not in {'0', 'false', 'no'}
    msg = EmailMessage()
    msg['Subject'] = 'Your Travel Buddy Finder password reset code'
    msg['From'] = sender
    msg['To'] = recipient
    msg.set_content(
        f'Your Travel Buddy Finder password reset code is: {code}\n\n'
        'This code expires in 10 minutes and can only be used once. '
        'If you did not request this, you can ignore this email.'
    )
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(msg)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    stage = 'verify' if session.get('password_reset_user_id') else 'request'
    if request.method == 'POST':
        action = request.form.get('action', 'send_otp')
        if action == 'send_otp':
            email = request.form.get('email', '').strip().lower()
            user = User.query.filter_by(email=email).first() if email else None
            # Use a generic message for unknown accounts to avoid exposing registered emails.
            if not user:
                flash('If an account exists for that email, a reset code will be sent.', 'info')
                return render_template('forgot_password.html', stage='request', email=email)
            recent_count = PasswordResetOTP.query.filter(
                PasswordResetOTP.user_id == user.id,
                PasswordResetOTP.created_at >= datetime.utcnow() - timedelta(minutes=15)
            ).count()
            if recent_count >= 3:
                flash('Too many reset requests. Please wait 15 minutes before trying again.', 'error')
                return render_template('forgot_password.html', stage='request', email=email)
            code = f'{secrets.randbelow(1_000_000):06d}'
            reset = PasswordResetOTP(
                user_id=user.id,
                code_hash=generate_password_hash(code),
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
            db.session.add(reset)
            db.session.commit()
            try:
                send_password_reset_email(user.email, code)
            except Exception as exc:
                db.session.delete(reset)
                db.session.commit()
                app.logger.exception('Password reset email could not be sent')
                flash('We could not send the email. Please check the SMTP settings in your .env file and try again.', 'error')
                return render_template('forgot_password.html', stage='request', email=email)
            session['password_reset_user_id'] = user.id
            flash('A 6-digit code was sent to your registered email. It expires in 10 minutes.', 'success')
            return render_template('forgot_password.html', stage='verify', email=email)

        if action == 'reset_password':
            user_id = session.get('password_reset_user_id')
            code = request.form.get('otp', '').strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')
            if not user_id:
                flash('Please request a new reset code first.', 'error')
                return redirect(url_for('forgot_password'))
            reset = PasswordResetOTP.query.filter_by(user_id=user_id, used=False).order_by(PasswordResetOTP.created_at.desc()).first()
            if not reset or reset.expires_at < datetime.utcnow() or reset.attempts >= 5:
                session.pop('password_reset_user_id', None)
                flash('That code has expired or is no longer valid. Request a new one.', 'error')
                return redirect(url_for('forgot_password'))
            reset.attempts += 1
            if not check_password_hash(reset.code_hash, code):
                db.session.commit()
                flash('The code is incorrect. Please check the email and try again.', 'error')
                return render_template('forgot_password.html', stage='verify', email='')
            if len(password) < 8:
                db.session.commit()
                flash('Choose a password with at least 8 characters.', 'error')
                return render_template('forgot_password.html', stage='verify', email='')
            if password != confirm:
                db.session.commit()
                flash('The passwords do not match.', 'error')
                return render_template('forgot_password.html', stage='verify', email='')
            user = db.session.get(User, user_id)
            if not user:
                session.pop('password_reset_user_id', None)
                flash('Account not found. Please try again.', 'error')
                return redirect(url_for('forgot_password'))
            user.password_hash = generate_password_hash(password)
            reset.used = True
            db.session.commit()
            session.pop('password_reset_user_id', None)
            flash('Your password has been reset. You can now log in.', 'success')
            return redirect(url_for('login'))
    return render_template('forgot_password.html', stage=stage, email='')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name','').strip(); email = request.form.get('email','').strip().lower()
        password = request.form.get('password',''); confirm = request.form.get('confirm_password','')
        if not name or not email or len(password) < 8:
            flash('Enter your name and email, and use a password with at least 8 characters.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('An account with that email already exists. Please log in.', 'error')
        else:
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user); db.session.commit(); session.clear(); session['user_id'] = user.id
            flash('Welcome aboard! Complete your profile and find your people.', 'success')
            return redirect(url_for('profile'))
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower(); password = request.form.get('password','')
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Incorrect email or password.', 'error')
        else:
            session.clear(); session['user_id'] = user.id
            flash(f'Welcome back, {user.name.split()[0]}!', 'success')
            return redirect(url_for('dashboard'))
    return render_template('auth.html', mode='login')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear(); flash('You have been logged out.', 'success'); return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    my_trips = Trip.query.filter_by(creator_id=user.id).order_by(Trip.created_at.desc()).all()
    joined = Membership.query.filter_by(user_id=user.id, status='accepted').all()
    pending = Membership.query.join(Trip).filter(Trip.creator_id==user.id, Membership.status=='pending').all()
    suggestions = Trip.query.filter(Trip.creator_id != user.id, Trip.status=='open').order_by(Trip.created_at.desc()).limit(3).all()
    return render_template('dashboard.html', user=user, my_trips=my_trips, joined=joined, pending=pending, suggestions=suggestions)

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    user = current_user()
    if request.method == 'POST' and request.form.get('action') == 'request_verification':
        document_type = request.form.get('document_type', '').strip()
        if document_type not in {'Passport', 'Driving licence', 'Voter ID', 'Other government ID'}:
            flash('Choose a valid government ID type.', 'error')
        elif request.form.get('verification_consent') != 'yes':
            flash('Please confirm that you understand the verification process.', 'error')
        else:
            latest = VerificationRequest.query.filter_by(user_id=user.id).order_by(VerificationRequest.created_at.desc()).first()
            if latest and latest.status in {'pending', 'verified'}:
                flash('You already have a pending or completed verification request.', 'info')
            else:
                db.session.add(VerificationRequest(user_id=user.id, document_type=document_type, status='pending'))
                db.session.commit()
                flash('Verification request submitted. Your status remains pending until an authorised reviewer checks it.', 'success')
        return redirect(url_for('profile'))
    if request.method == 'POST':
        user.name=request.form.get('name','').strip() or user.name
        user.city=request.form.get('city','').strip()
        user.bio=request.form.get('bio','').strip()[:500]
        user.interests=request.form.get('interests','').strip()[:300]
        user.travel_style=request.form.get('travel_style','Flexible')
        try: user.budget=max(0, int(request.form.get('budget', 15000)))
        except ValueError: user.budget=15000
        db.session.commit(); flash('Profile saved!', 'success'); return redirect(url_for('profile'))
    verification = VerificationRequest.query.filter_by(user_id=user.id).order_by(VerificationRequest.created_at.desc()).first()
    return render_template('profile.html', user=user, verification=verification)

@app.route('/buddies')
@login_required
def buddies():
    query=User.query.filter(User.id != current_user().id)
    destination=request.args.get('destination','').strip()
    style=request.args.get('style','').strip()
    max_budget=request.args.get('max_budget','').strip()
    if style: query=query.filter(User.travel_style==style)
    if max_budget.isdigit(): query=query.filter(User.budget <= int(max_budget))
    users=query.order_by(User.created_at.desc()).all()
    verified_ids={r.user_id for r in VerificationRequest.query.filter_by(status='verified').all()}
    cards=[]
    for u in users:
        mine={x.strip().lower() for x in current_user().interests.split(',') if x.strip()}
        theirs={x.strip().lower() for x in u.interests.split(',') if x.strip()}
        shared=mine & theirs
        score=35 + (25 if current_user().budget and abs(current_user().budget-u.budget) <= max(5000,current_user().budget*.25) else 0) + min(30, len(shared)*10) + (10 if current_user().travel_style==u.travel_style else 0)
        cards.append({'user':u,'score':min(99,score),'shared':sorted(shared),'verified':u.id in verified_ids})
    if destination:
        cards=[c for c in cards if destination.lower() in (c['user'].bio+' '+c['user'].interests+' '+c['user'].city).lower()]
    return render_template('buddies.html', cards=cards, destination=destination, style=style, max_budget=max_budget)

@app.route('/maps')
def google_maps():
    """Search destinations and open map/directions links through Google Maps."""
    destination = (request.args.get('destination') or '').strip()[:180]
    start_location = (request.args.get('start_location') or '').strip()[:180]
    search_query = (request.args.get('search_query') or '').strip()[:180]
    map_query = destination or search_query or 'popular travel destinations in India'
    map_embed_url = 'https://maps.google.com/maps?q=' + quote_plus(map_query) + '&output=embed'
    places_url = 'https://www.google.com/maps/search/?api=1&query=' + quote_plus(search_query or destination or 'tourist attractions')
    directions_url = None
    if destination:
        directions_url = 'https://www.google.com/maps/dir/?api=1&destination=' + quote_plus(destination)
        if start_location:
            directions_url += '&origin=' + quote_plus(start_location)
            directions_url += '&travelmode=driving'
    return render_template('maps.html', destination=destination, start_location=start_location,
                           search_query=search_query, map_query=map_query, map_embed_url=map_embed_url,
                           places_url=places_url, directions_url=directions_url)


@app.route('/trips')
def trips():
    q=Trip.query.filter_by(status='open')
    dest=request.args.get('destination','').strip(); max_budget=request.args.get('max_budget','').strip()
    if dest: q=q.filter(Trip.destination.ilike(f'%{dest}%'))
    if max_budget.isdigit(): q=q.filter(Trip.budget <= int(max_budget))
    all_trips=alternate_domestic_international(q.order_by(Trip.created_at.desc()).all())
    # Explore Trips uses a title-aware image map so city trips get city-appropriate
    # photos instead of rotating to an unrelated destination just to avoid duplicates.
    # IDs are kept unique across the seeded trip cards; a fallback pool is only used
    # for user-created trips whose destination/title has no dedicated image.
    trip_photo_ids = {
        'himalayan escape': 'photo-1500530855697-b586d89ba3ee',
        'goa beach': 'photo-1500375592092-40eb2168fd21',
        'kerala backwater': 'photo-1602216056096-3b40cc0c9944',
        'jaipur heritage': 'photo-1477587458883-47145ed94245',
        'rishikesh adventure': 'photo-1500534623283-312aade485b7',
        'manali snow': 'photo-1464278533981-50106e6176b1',
        'udaipur lakeside': 'photo-1514222134-b57cbb8ce073',
        'meghalaya cloud': 'photo-1441974231531-c6227db76b6e',
        'mumbai arts': 'photo-1570168007204-dfb528c6958f',
        'andaman blue': 'photo-1507525428034-b723cf961d3e',
        'varanasi culture': 'photo-1561361513-2d000a50f0dc',
        'coorg green': 'photo-1448375240586-882707db888b',
        'spiti valley': 'photo-1501785888041-af3ef285b470',
        'agra & fatehpur': 'photo-1564507592333-c60657eea523',
        'pondicherry slow': 'photo-1494783367193-149034c05e8f',
        'tokyo neon': 'photo-1540959733332-eab4deabeeaf',
        'kyoto temples': 'photo-1493976040374-85c8e12f0c0e',
        'bali beaches': 'photo-1537996194471-e657df975ab4',
        'paris art': 'photo-1502602898657-3e91760cbb34',
        'lisbon coast': 'photo-1555881400-74d7acaacd8b',
        'swiss alps': 'photo-1531366936337-7c912a4589a7',
        'bangkok street': 'photo-1508009603885-50cf7c579365',
        'istanbul between': 'photo-1524231757912-21f4fe3a7200',
        'cape town coast': 'photo-1580060839134-75a5edca2e99',
        'singapore city': 'photo-1525625293386-3f8f99389edd',
        'sydney harbour': 'photo-1506973035872-a4ec16b8e8d9',
        'mysuru palace': 'photo-1600100397608-f010f1c8e8d8',
        'rome food': 'photo-1552832230-c0197dd311b5',
        'darjeeling toy': 'photo-1519681393784-d120267933ba',
        'barcelona art': 'photo-1539037116277-4db20889f2d4',
        'hampi heritage': 'photo-1606293926075-69a00dbfde81',
        'london neighbourhood': 'photo-1513635269975-59663e0ac1ad',
        'sikkim lakes': 'photo-1464822759023-fed622ff2c3b',
        'dubai skyline': 'photo-1512453979798-5ea266f8880c',
        'puducherry coastal': 'photo-1519046904884-53103b34b206',
        'seoul street': 'photo-1517154421773-0529f29ea451',
        'kutch white desert': 'photo-1509316785289-025f5b846b35',
        'kathmandu valley': 'photo-1544735716-392fe2489ffa',
        'orchha forts': 'photo-1567157577867-05fb8f25dee9',
        'maldives island': 'photo-1514282401047-d79a71a590e8',
        'ziro valley': 'photo-1472396961693-142e6e269027',
        'prague old town': 'photo-1541849546-216549ae216d',
        'lakshadweep lagoon': 'photo-1510414842594-a61c69b5ae57',
        'vienna music': 'photo-1516550893923-42d28e5677af',
        'jodhpur blue': 'photo-1599661046827-dacff0c0f09a',
        'vancouver trails': 'photo-1503614472-8c93d56cdab4',
    }
    used_image_ids=set()
    trip_image_urls={}
    image_pool=list(dict.fromkeys(PLACE_IMAGE_IDS.values()))
    for index, trip in enumerate(all_trips):
        title_key=(trip.title or '').strip().lower()
        image_id=next((photo_id for phrase, photo_id in trip_photo_ids.items() if title_key.startswith(phrase)), None)
        if image_id is None:
            preferred_url=destination_image(trip.destination, 0)
            image_id=preferred_url.split('/')[3].split('?')[0]
        if image_id in used_image_ids:
            # Use another unused photo only as a last resort; known seeded titles above
            # each have dedicated assignments so their images stay destination-relevant.
            image_id=next((candidate for candidate in image_pool if candidate not in used_image_ids), image_id)
        used_image_ids.add(image_id)
        trip_image_urls[trip.id]=f'https://images.unsplash.com/{image_id}?auto=format&fit=crop&w=1200&q=85'
    return render_template('trips.html', trips=all_trips, destination=dest, max_budget=max_budget, trip_image_urls=trip_image_urls)

@app.route('/trips/create', methods=['GET','POST'])
@login_required
def create_trip():
    if request.method=='POST':
        title=request.form.get('title','').strip(); dest=request.form.get('destination','').strip()
        start=request.form.get('start_date',''); end=request.form.get('end_date','')
        if not title or not dest or not start or not end or end < start:
            flash('Please enter a title, destination, and valid travel dates.', 'error')
        else:
            try: budget=max(0,int(request.form.get('budget',0))); cap=min(30,max(2,int(request.form.get('max_members',4))))
            except ValueError: budget=0; cap=4
            trip=Trip(title=title,destination=dest,start_location=request.form.get('start_location','').strip(),start_date=start,end_date=end,budget=budget,description=request.form.get('description','').strip(),interests=request.form.get('interests','').strip(),max_members=cap,creator_id=current_user().id)
            db.session.add(trip); db.session.commit(); flash('Trip created! Add your planned costs in the trip workspace.', 'success'); return redirect(url_for('trip_detail', trip_id=trip.id))
    return render_template('create_trip.html')

@app.route('/trips/<int:trip_id>')
def trip_detail(trip_id):
    trip=db.session.get(Trip,trip_id)
    if not trip: abort(404)
    user=current_user(); membership=None
    if user: membership=Membership.query.filter_by(trip_id=trip.id,user_id=user.id).first()
    expenses=Expense.query.filter_by(trip_id=trip.id).order_by(Expense.created_at.desc()).all()
    categories=expense_totals(trip); total=sum(categories.values())
    items=ItineraryItem.query.filter_by(trip_id=trip.id).order_by(ItineraryItem.day,ItineraryItem.time).all()
    members=Membership.query.filter_by(trip_id=trip.id,status='accepted').all()
    pending=Membership.query.filter_by(trip_id=trip.id,status='pending').all() if user and user.id==trip.creator_id else []
    return render_template('trip_detail.html', trip=trip, membership=membership, expenses=expenses, categories=categories,total=total,items=items,members=members,pending=pending)

@app.route('/trips/<int:trip_id>/join', methods=['POST'])
@login_required
def join_trip(trip_id):
    trip=db.session.get(Trip,trip_id)
    if not trip: abort(404)
    user=current_user()
    if trip.creator_id==user.id: flash('You already organize this trip.', 'info')
    elif trip.status!='open': flash('This trip is not open for requests.', 'error')
    elif Membership.query.filter_by(trip_id=trip.id,user_id=user.id).first(): flash('You have already requested or joined this trip.', 'info')
    elif len([m for m in trip.memberships if m.status=='accepted']) >= trip.max_members-1: flash('This trip is full.', 'error')
    else: db.session.add(Membership(trip_id=trip.id,user_id=user.id,status='pending')); db.session.commit(); flash('Join request sent to the trip organiser.', 'success')
    return redirect(url_for('trip_detail',trip_id=trip.id))

@app.route('/trips/<int:trip_id>/requests/<int:request_id>/<action>', methods=['POST'])
@login_required
def manage_join(trip_id,request_id,action):
    trip=db.session.get(Trip,trip_id); req=db.session.get(Membership,request_id)
    if not trip or trip.creator_id!=current_user().id: abort(403)
    if not req or req.trip_id!=trip.id or req.status!='pending' or action not in ('accept','reject'): abort(404)
    if action=='accept' and len([m for m in trip.memberships if m.status=='accepted']) >= trip.max_members-1:
        flash('The trip has reached its member limit.', 'error')
    else: req.status='accepted' if action=='accept' else 'rejected'; db.session.commit(); flash('Request updated.', 'success')
    return redirect(url_for('trip_detail',trip_id=trip.id))

@app.route('/trips/<int:trip_id>/expenses', methods=['POST'])
@login_required
def add_expense(trip_id):
    trip=trip_access(trip_id); title=request.form.get('title','').strip(); category=request.form.get('category','Other')
    try: amount=float(request.form.get('amount',0))
    except ValueError: amount=0
    if category not in ('Accommodation','Transportation','Activities','Food','Other') or not title or amount<=0 or amount>100000000:
        flash('Enter a valid expense name, category, and amount.', 'error')
    else:
        db.session.add(Expense(trip_id=trip.id,added_by=current_user().id,category=category,title=title,amount=amount,details=request.form.get('details','').strip()[:400])); db.session.commit(); flash('Expense added to the shared budget.', 'success')
    return redirect(url_for('trip_detail',trip_id=trip.id)+'#budget')

@app.route('/trips/<int:trip_id>/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete_expense(trip_id,expense_id):
    trip=trip_access(trip_id); exp=db.session.get(Expense,expense_id)
    if not exp or exp.trip_id!=trip.id: abort(404)
    if exp.added_by!=current_user().id and trip.creator_id!=current_user().id: abort(403)
    db.session.delete(exp); db.session.commit(); flash('Expense removed.', 'success'); return redirect(url_for('trip_detail',trip_id=trip.id)+'#budget')

@app.route('/trips/<int:trip_id>/expenses/<int:expense_id>/edit', methods=['POST'])
@login_required
def edit_expense(trip_id, expense_id):
    trip = trip_access(trip_id)
    exp = db.session.get(Expense, expense_id)
    if not exp or exp.trip_id != trip.id:
        abort(404)
    if exp.added_by != current_user().id and trip.creator_id != current_user().id:
        abort(403)
    title = request.form.get('title', '').strip()
    category = request.form.get('category', 'Other')
    details = request.form.get('details', '').strip()[:400]
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        amount = 0
    if not title or amount <= 0 or amount > 100000000 or category not in ('Accommodation','Transportation','Activities','Food','Other'):
        flash('Please enter a valid name, category and amount.', 'error')
    else:
        exp.title, exp.category, exp.amount, exp.details = title, category, amount, details
        db.session.commit()
        flash('Expense updated. Shared budget recalculated.', 'success')
    return redirect(url_for('trip_detail', trip_id=trip.id) + '#budget')

@app.route('/trips/<int:trip_id>/itinerary', methods=['POST'])
@login_required
def add_itinerary(trip_id):
    trip=trip_access(trip_id); title=request.form.get('title','').strip(); day=request.form.get('day','').strip()
    if not title or not day: flash('Add an activity and day.', 'error')
    else:
        try: cost=max(0,float(request.form.get('cost',0)))
        except ValueError: cost=0
        db.session.add(ItineraryItem(trip_id=trip.id,added_by=current_user().id,day=day,title=title,time=request.form.get('time',''),notes=request.form.get('notes','').strip()[:500],cost=cost));
        if cost>0: db.session.add(Expense(trip_id=trip.id,added_by=current_user().id,category='Activities',title=title,amount=cost,details='Added from itinerary'))
        db.session.commit(); flash('Itinerary updated.', 'success')
    return redirect(url_for('trip_detail',trip_id=trip.id)+'#itinerary')

CATALOG = {
    'stays': {
        'title': 'Stays & accommodation', 'subtitle': 'Guesthouses, hostels and stays to fit your travel style.', 'category': 'Accommodation',
        'items': [
            {'name':'Mountain View Homestay','image_url':'https://images.unsplash.com/photo-1510798831971-661eb04b3739?auto=format&fit=crop&w=1200&q=85','place':'Leh, Ladakh','price':1800,'unit':'per room / night','type':'Homestay','desc':'Warm local hospitality with mountain views. Sample estimate.', 'image':'photo-mountain'},
            {'name':'Pangong Lakeside Camp','image_url':'https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?auto=format&fit=crop&w=1200&q=85','place':'Pangong Lake, Ladakh','price':3200,'unit':'per tent / night','type':'Camp','desc':'A lakeside overnight experience. Sample estimate.', 'image':'photo-lake'},
            {'name':'Old Goa Heritage Guesthouse','image_url':'https://images.unsplash.com/photo-1564013799919-ab600027ffc6?auto=format&fit=crop&w=1200&q=85','place':'North Goa','price':2200,'unit':'per room / night','type':'Guesthouse','desc':'A relaxed base near cafés and heritage streets. Sample estimate.','image':'photo-coast'},
            {'name':'Backwater Eco Stay','image_url':'https://images.unsplash.com/photo-1499793983690-e29da59ef1c2?auto=format&fit=crop&w=1200&q=85','place':'Alleppey, Kerala','price':2600,'unit':'per room / night','type':'Eco stay','desc':'Quiet stay close to Kerala backwaters. Sample estimate.','image':'photo-forest'},
            {'name':'Pink City Boutique Stay','image_url':'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=85','place':'Jaipur, Rajasthan','price':2400,'unit':'per room / night','type':'Boutique hotel','desc':'A colourful heritage-inspired stay. Sample estimate.','image':'photo-city'},
            {'name':'Rishikesh Riverside Hostel','image_url':'https://images.unsplash.com/photo-1555854877-bab0e564b8d5?auto=format&fit=crop&w=1200&q=85','place':'Rishikesh, Uttarakhand','price':750,'unit':'per bed / night','type':'Hostel','desc':'Social common areas for solo travellers. Sample estimate.','image':'photo-river'},
            {'name':'Shinjuku City Hotel','image_url':'https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=1200&q=85','place':'Tokyo, Japan','price':7800,'unit':'per room / night','type':'City hotel','desc':'A convenient base for metro connections and city exploring. Illustrative estimate.'},
            {'name':'Ubud Garden Guesthouse','image_url':'https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=1200&q=85','place':'Ubud, Bali, Indonesia','price':4200,'unit':'per room / night','type':'Guesthouse','desc':'A relaxed stay near cafés and green landscapes. Illustrative estimate.'},
            {'name':'Paris Left Bank Apartment','image_url':'https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1200&q=85','place':'Paris, France','price':11500,'unit':'per room / night','type':'Apartment','desc':'Apartment-style base for exploring museums and neighbourhoods. Illustrative estimate.'},
            {'name':'Alpine Guesthouse','image_url':'https://images.unsplash.com/photo-1517760444937-f6397edcbbcd?auto=format&fit=crop&w=1200&q=85','place':'Interlaken, Switzerland','price':12500,'unit':'per room / night','type':'Guesthouse','desc':'A cosy base for mountain and lake outings. Illustrative estimate.'}]},
    'transportation': {
        'title':'Transportation', 'subtitle':'Compare travel modes and add an estimate to your trip budget.', 'category':'Transportation',
        'items':[
            {'name':'Shared SUV from Leh','image_url':'https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1200&q=85','place':'Leh → Nubra Valley','price':2800,'unit':'per person return','type':'Shared cab','desc':'A shared road-trip estimate; route and availability must be confirmed.','image':'photo-mountain'},
            {'name':'Airport transfer','image_url':'https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?auto=format&fit=crop&w=1200&q=85','place':'Leh Airport → Leh town','price':600,'unit':'per vehicle','type':'Cab transfer','desc':'Estimated local transfer fare. Confirm with the provider.','image':'photo-road'},
            {'name':'Sleeper bus','image_url':'https://images.unsplash.com/photo-1570125909232-eb263c188f7e?auto=format&fit=crop&w=1200&q=85','place':'Delhi → Manali','price':1100,'unit':'per person one way','type':'Bus','desc':'Sample fare only; not a live ticket price.','image':'photo-road'},
            {'name':'Scooter rental','image_url':'https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=85','place':'North Goa','price':500,'unit':'per day','type':'Rental','desc':'Sample daily estimate; licence and deposit may be required.','image':'photo-coast'},
            {'name':'Local auto & cab fund','image_url':'https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=1200&q=85','place':'Jaipur city','price':900,'unit':'per day per group','type':'Local transport','desc':'Flexible local travel allowance. Sample estimate.','image':'photo-city'},
            {'name':'Backwater boat transfer','image_url':'https://images.unsplash.com/photo-1500375592092-40eb2168fd21?auto=format&fit=crop&w=1200&q=85','place':'Alleppey','price':1500,'unit':'per group','type':'Boat','desc':'Estimated transfer / short boat ride.','image':'photo-river'},
            {'name':'Tokyo Metro Day Pass','image_url':'https://images.unsplash.com/photo-1533929736458-ca588d08c8be?auto=format&fit=crop&w=1200&q=85','place':'Tokyo, Japan','price':650,'unit':'per person / day','type':'Metro','desc':'Budget allowance for getting around the city; check current pass rules.'},
            {'name':'Bali Airport Transfer','image_url':'https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?auto=format&fit=crop&w=1200&q=85','place':'Denpasar Airport → Ubud, Bali','price':2200,'unit':'per vehicle','type':'Private transfer','desc':'Illustrative one-way transfer estimate; confirm with a provider.'},
            {'name':'Paris Metro & Bus Allowance','image_url':'https://images.unsplash.com/photo-1570125909232-eb263c188f7e?auto=format&fit=crop&w=1200&q=85','place':'Paris, France','price':900,'unit':'per person / day','type':'Public transport','desc':'Planning allowance only; ticket options and fares change.'},
            {'name':'Swiss Regional Train Allowance','image_url':'https://images.unsplash.com/photo-1474487548417-781cb71495f3?auto=format&fit=crop&w=1200&q=85','place':'Interlaken region, Switzerland','price':4500,'unit':'per person / day','type':'Train','desc':'Illustrative transport budget; routes and passes affect final cost.'}]},
    'activities': {
        'title':'Activities & experiences','subtitle':'Add memorable experiences to your itinerary and shared budget.', 'category':'Activities',
        'items':[
            {'name':'Pangong Lake day trip','image_url':'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=85','place':'Ladakh','price':1200,'unit':'per person','type':'Nature','desc':'Lakeside stops and photography time. Sample estimate.','image':'photo-lake'},
            {'name':'Monastery trail','image_url':'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1200&q=85','place':'Leh, Ladakh','price':650,'unit':'per person','type':'Culture','desc':'Visit local monasteries and learn about the region.','image':'photo-mountain'},
            {'name':'Sunset kayaking','image_url':'https://images.unsplash.com/photo-1500375592092-40eb2168fd21?auto=format&fit=crop&w=1200&q=85','place':'North Goa','price':950,'unit':'per person','type':'Water activity','desc':'Estimated guided session; weather dependent.','image':'photo-coast'},
            {'name':'Tea garden walk','image_url':'https://images.unsplash.com/photo-1515586000433-45406d8e6662?auto=format&fit=crop&w=1200&q=85','place':'Munnar, Kerala','price':500,'unit':'per person','type':'Nature','desc':'A guided walk through scenic tea gardens.','image':'photo-forest'},
            {'name':'Amber Fort & old city','image_url':'https://images.unsplash.com/photo-1524492412937-b28074a5d7da?auto=format&fit=crop&w=1200&q=85','place':'Jaipur, Rajasthan','price':800,'unit':'per person','type':'Culture','desc':'Heritage sightseeing allowance. Entry fees may vary.','image':'photo-city'},
            {'name':'River rafting','image_url':'https://images.unsplash.com/photo-1530866495561-507c9faab2ed?auto=format&fit=crop&w=1200&q=85','place':'Rishikesh','price':1200,'unit':'per person','type':'Adventure','desc':'Sample estimate; only use licensed operators and check conditions.','image':'photo-river'}]}}


# Expanded India + international catalog options. Each catalog card uses a distinct photo URL.
CATALOG['stays']['items'].extend([
 {'name':'Hampi Heritage Courtyard Stay','image_url':'https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=1200&q=85','place':'Hampi, Karnataka, India','price':2100,'unit':'per room / night','type':'Heritage homestay','desc':'A simple base for exploring the historic landscape.'},
 {'name':'Darjeeling Tea Garden Lodge','image_url':'https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=85','place':'Darjeeling, India','price':2900,'unit':'per room / night','type':'Lodge','desc':'Mountain views and a cosy place to rest.'},
 {'name':'Barcelona Boutique Guesthouse','image_url':'https://images.unsplash.com/photo-1566933293069-b55c7f326dd4?auto=format&fit=crop&w=1200&q=85','place':'Barcelona, Spain','price':9800,'unit':'per room / night','type':'Guesthouse','desc':'A city base near architecture, food and the waterfront.'},
 {'name':'London Social Hostel','image_url':'https://images.unsplash.com/photo-1570125909232-eb263c188f7e?auto=format&fit=crop&w=1200&q=85','place':'London, United Kingdom','price':6500,'unit':'per bed / night','type':'Hostel','desc':'A shared stay option for budget-conscious explorers.'},
 {'name':'Seoul Design Hotel','image_url':'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1200&q=85','place':'Seoul, South Korea','price':7200,'unit':'per room / night','type':'City hotel','desc':'Convenient base for food streets and public transport.'},
 {'name':'Kathmandu Garden Guesthouse','image_url':'https://images.unsplash.com/photo-1500534623283-312aadec9f1d?auto=format&fit=crop&w=1200&q=85','place':'Kathmandu, Nepal','price':2600,'unit':'per room / night','type':'Guesthouse','desc':'A relaxed base for cultural sights and valley walks.'},
 {'name':'Dubai Marina Apartment','image_url':'https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=1200&q=85','place':'Dubai, UAE','price':10500,'unit':'per room / night','type':'Apartment','desc':'Apartment-style accommodation for a city break.'},
 {'name':'Maldives Island Bungalow','image_url':'https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1200&q=85','place':'Maldives','price':22000,'unit':'per room / night','type':'Island bungalow','desc':'An illustrative island-stay estimate; confirm transfers and inclusions.'},
])
CATALOG['transportation']['items'].extend([
 {'name':'Mysuru Intercity Train','image_url':'https://images.unsplash.com/photo-1510414842594-a61c69b5ae57?auto=format&fit=crop&w=1200&q=85','place':'Bengaluru → Mysuru, India','price':450,'unit':'per person one way','type':'Train','desc':'Illustrative rail fare; check current schedules and ticket prices.'},
 {'name':'Barcelona Metro Day Budget','image_url':'https://images.unsplash.com/photo-1464278533981-50106e6176b1?auto=format&fit=crop&w=1200&q=85','place':'Barcelona, Spain','price':850,'unit':'per person / day','type':'Metro','desc':'Planning allowance only; current ticket products may differ.'},
 {'name':'London Underground Allowance','image_url':'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=85','place':'London, United Kingdom','price':1600,'unit':'per person / day','type':'Metro and bus','desc':'Illustrative transit budget; fares depend on zones and payment method.'},
 {'name':'Seoul Metro & Bus Budget','image_url':'https://images.unsplash.com/photo-1472396961693-142e6e269027?auto=format&fit=crop&w=1200&q=85','place':'Seoul, South Korea','price':600,'unit':'per person / day','type':'Metro and bus','desc':'Sample local transit allowance, not a live fare.'},
 {'name':'Nepal Tourist Bus','image_url':'https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=1200&q=85','place':'Kathmandu → Pokhara, Nepal','price':1800,'unit':'per person one way','type':'Tourist bus','desc':'Illustrative route budget; operator, season and class affect price.'},
 {'name':'Dubai Metro & Tram Allowance','image_url':'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=85','place':'Dubai, UAE','price':900,'unit':'per person / day','type':'Metro and tram','desc':'Planning estimate only; check zones and current fares.'},
 {'name':'Rome Public Transport Budget','image_url':'https://images.unsplash.com/photo-1530789253388-582c481c54b0?auto=format&fit=crop&w=1200&q=85','place':'Rome, Italy','price':800,'unit':'per person / day','type':'Metro and bus','desc':'Illustrative local transport allowance.'},
 {'name':'Sydney Ferry & Train Budget','image_url':'https://images.unsplash.com/photo-1493246507139-91e8fad9978e?auto=format&fit=crop&w=1200&q=85','place':'Sydney, Australia','price':1400,'unit':'per person / day','type':'Train and ferry','desc':'Sample daily transit allowance; fares vary by route.'},
])
CATALOG['activities']['items'].extend([
 {'name':'Hampi Sunrise Heritage Walk','image_url':'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1200&q=85','place':'Hampi, India','price':700,'unit':'per person','type':'Heritage walk','desc':'Suggested guided walk; verify guide and entry fees.'},
 {'name':'Barcelona Architecture Walk','image_url':'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1200&q=85','place':'Barcelona, Spain','price':1800,'unit':'per person','type':'Architecture','desc':'Explore distinctive city architecture; guided tours cost extra.'},
 {'name':'London Museum & Market Day','image_url':'https://images.unsplash.com/photo-1500534314209-a25okw1d9e8?auto=format&fit=crop&w=1200&q=85','place':'London, United Kingdom','price':1500,'unit':'per person','type':'Culture','desc':'Budget for local transport, food and optional paid exhibitions.'},
 {'name':'Seoul Night Market Food Trail','image_url':'https://images.unsplash.com/photo-1469474968028-56623f02e42e?auto=format&fit=crop&w=1200&q=85','place':'Seoul, South Korea','price':1600,'unit':'per person','type':'Food tour','desc':'Sample budget for tasting local street food.'},
 {'name':'Kathmandu Heritage Squares','image_url':'https://images.unsplash.com/photo-1518837695005-2083093ee35b?auto=format&fit=crop&w=1200&q=85','place':'Kathmandu, Nepal','price':900,'unit':'per person','type':'Culture','desc':'Plan for local guiding and any applicable entry tickets.'},
 {'name':'Dubai Creek & Souk Walk','image_url':'https://images.unsplash.com/photo-1473116763249-2faaef81ccda?auto=format&fit=crop&w=1200&q=85','place':'Dubai, UAE','price':1200,'unit':'per person','type':'Culture','desc':'Old-town walk and waterfront area; boat ride may cost extra.'},
 {'name':'Mysuru Palace & Market Visit','image_url':'https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=1200&q=85','place':'Mysuru, India','price':850,'unit':'per person','type':'Culture','desc':'Suggested palace and market visit; entry fees may change.'},
 {'name':'Swiss-Style Lake Day in Vancouver','image_url':'https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1200&q=85','place':'Vancouver, Canada','price':2500,'unit':'per person','type':'Nature','desc':'Suggested waterfront and nature day; transport and tours extra.'},
])

PACKAGES = [{'name': 'Ladakh: High Passes & Blue Lakes', 'destination': 'Ladakh, India', 'days': '5 days / 4 nights', 'price': 45999, 'style': 'Adventure', 'image_url': 'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=85', 'image': 'place-1', 'description': 'High-altitude lakes, monasteries and mountain drives in Ladakh.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Ladakh, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Ladakh, India', 'Day 3 · Food, culture and experiences around Ladakh, India', 'Day 4 · Flexible nature, heritage or guided day trip in Ladakh, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Japan: Temples, Gardens & Rail', 'destination': 'Japan', 'days': '5 days / 4 nights', 'price': 94999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=1200&q=85', 'image': 'place-2', 'description': 'Traditional streets, gardens, food culture and efficient rail journeys.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Japan and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Japan', 'Day 3 · Food, culture and experiences around Japan', 'Day 4 · Flexible nature, heritage or guided day trip in Japan', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Kerala: Backwaters & Green Escapes', 'destination': 'Kerala, India', 'days': '6 days / 5 nights', 'price': 32999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1602216056096-3b40cc0c9944?auto=format&fit=crop&w=1200&q=85', 'image': 'place-3', 'description': 'Backwater cruises, coastal villages, local cuisine and lush landscapes.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Kerala, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Kerala, India', 'Day 3 · Food, culture and experiences around Kerala, India', 'Day 4 · Flexible nature, heritage or guided day trip in Kerala, India', 'Day 5 · Optional excursion and relaxed evening in Kerala, India', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'France: Art, Cafés & Countryside', 'destination': 'France', 'days': '5 days / 4 nights', 'price': 109999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1502602898657-3e91760cbb34?auto=format&fit=crop&w=1200&q=85', 'image': 'place-4', 'description': 'Architecture, museums, café culture and countryside day trips.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in France and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in France', 'Day 3 · Food, culture and experiences around France', 'Day 4 · Flexible nature, heritage or guided day trip in France', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Jaipur: Forts, Bazaars & Food', 'destination': 'Jaipur, India', 'days': '5 days / 4 nights', 'price': 27999, 'style': 'Heritage', 'image_url': 'https://images.unsplash.com/photo-1477587458883-47145ed94245?auto=format&fit=crop&w=1200&q=85', 'image': 'place-5', 'description': 'Pink City heritage, forts, markets, crafts and Rajasthani cuisine.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Jaipur, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Jaipur, India', 'Day 3 · Food, culture and experiences around Jaipur, India', 'Day 4 · Flexible nature, heritage or guided day trip in Jaipur, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Switzerland: Alpine Rail & Lakes', 'destination': 'Switzerland', 'days': '6 days / 5 nights', 'price': 144999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1531366936337-7c912a4589a7?auto=format&fit=crop&w=1200&q=85', 'image': 'place-6', 'description': 'Alpine scenery, lakeside walks and scenic public transport.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Switzerland and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Switzerland', 'Day 3 · Food, culture and experiences around Switzerland', 'Day 4 · Flexible nature, heritage or guided day trip in Switzerland', 'Day 5 · Optional excursion and relaxed evening in Switzerland', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Goa: Beaches & Coastal Culture', 'destination': 'Goa, India', 'days': '5 days / 4 nights', 'price': 29999, 'style': 'Relaxed', 'image_url': 'https://images.unsplash.com/photo-1500375592092-40eb2168fd21?auto=format&fit=crop&w=1200&q=85', 'image': 'place-7', 'description': 'Beach time, Portuguese heritage, seafood and relaxed coastal days.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Goa, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Goa, India', 'Day 3 · Food, culture and experiences around Goa, India', 'Day 4 · Flexible nature, heritage or guided day trip in Goa, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Italy: Ancient Streets & Food', 'destination': 'Italy', 'days': '5 days / 4 nights', 'price': 119999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1552832230-c0197dd311b5?auto=format&fit=crop&w=1200&q=85', 'image': 'place-8', 'description': 'Historic architecture, regional food, piazzas and art.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Italy and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Italy', 'Day 3 · Food, culture and experiences around Italy', 'Day 4 · Flexible nature, heritage or guided day trip in Italy', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Rishikesh: River & Himalayan Foothills', 'destination': 'Rishikesh, India', 'days': '6 days / 5 nights', 'price': 24999, 'style': 'Adventure', 'image_url': 'https://images.unsplash.com/photo-1500534623283-312aade485b7?auto=format&fit=crop&w=1200&q=85', 'image': 'place-9', 'description': 'River views, guided walks, yoga and outdoor activities.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Rishikesh, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Rishikesh, India', 'Day 3 · Food, culture and experiences around Rishikesh, India', 'Day 4 · Flexible nature, heritage or guided day trip in Rishikesh, India', 'Day 5 · Optional excursion and relaxed evening in Rishikesh, India', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Thailand: Markets, Temples & Islands', 'destination': 'Thailand', 'days': '5 days / 4 nights', 'price': 61999, 'style': 'Food & Culture', 'image_url': 'https://images.unsplash.com/photo-1508009603885-50cf7c579365?auto=format&fit=crop&w=1200&q=85', 'image': 'place-10', 'description': 'Street food, temple visits, local markets and optional island time.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Thailand and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Thailand', 'Day 3 · Food, culture and experiences around Thailand', 'Day 4 · Flexible nature, heritage or guided day trip in Thailand', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Udaipur: Lakes & Palace Heritage', 'destination': 'Udaipur, India', 'days': '5 days / 4 nights', 'price': 26999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1514222134-b57cbb8ce073?auto=format&fit=crop&w=1200&q=85', 'image': 'place-11', 'description': 'Lakefront scenery, palace architecture, crafts and local cuisine.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Udaipur, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Udaipur, India', 'Day 3 · Food, culture and experiences around Udaipur, India', 'Day 4 · Flexible nature, heritage or guided day trip in Udaipur, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Spain: Architecture & Mediterranean Days', 'destination': 'Spain', 'days': '6 days / 5 nights', 'price': 114999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1539037116277-4db20889f2d4?auto=format&fit=crop&w=1200&q=85', 'image': 'place-12', 'description': 'Architecture, markets, coastlines and late-evening food culture.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Spain and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Spain', 'Day 3 · Food, culture and experiences around Spain', 'Day 4 · Flexible nature, heritage or guided day trip in Spain', 'Day 5 · Optional excursion and relaxed evening in Spain', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Andaman: Coral Reefs & Island Life', 'destination': 'Andaman and Nicobar Islands, India', 'days': '5 days / 4 nights', 'price': 38999, 'style': 'Relaxed', 'image_url': 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=85', 'image': 'place-13', 'description': 'Island beaches, clear water, snorkelling and marine landscapes.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Andaman and Nicobar Islands, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Andaman and Nicobar Islands, India', 'Day 3 · Food, culture and experiences around Andaman and Nicobar Islands, India', 'Day 4 · Flexible nature, heritage or guided day trip in Andaman and Nicobar Islands, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Canada: Lakes, Forests & City Life', 'destination': 'Canada', 'days': '5 days / 4 nights', 'price': 149999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1503614472-8c93d56cdab4?auto=format&fit=crop&w=1200&q=85', 'image': 'place-14', 'description': 'Lake scenery, forest trails, wildlife and welcoming city stops.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Canada and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Canada', 'Day 3 · Food, culture and experiences around Canada', 'Day 4 · Flexible nature, heritage or guided day trip in Canada', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Darjeeling: Tea Gardens & Mountain Views', 'destination': 'Darjeeling, India', 'days': '6 days / 5 nights', 'price': 23999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1200&q=85', 'image': 'place-15', 'description': 'Tea estates, mountain viewpoints, heritage rail and local cafés.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Darjeeling, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Darjeeling, India', 'Day 3 · Food, culture and experiences around Darjeeling, India', 'Day 4 · Flexible nature, heritage or guided day trip in Darjeeling, India', 'Day 5 · Optional excursion and relaxed evening in Darjeeling, India', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Indonesia: Islands & Rice Terraces', 'destination': 'Indonesia', 'days': '5 days / 4 nights', 'price': 67999, 'style': 'Relaxed', 'image_url': 'https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=1200&q=85', 'image': 'place-16', 'description': 'Temple visits, rice terraces, island scenery and coastal days.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Indonesia and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Indonesia', 'Day 3 · Food, culture and experiences around Indonesia', 'Day 4 · Flexible nature, heritage or guided day trip in Indonesia', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Hampi: Ancient Ruins & Bouldered Landscapes', 'destination': 'Hampi, India', 'days': '5 days / 4 nights', 'price': 21999, 'style': 'Heritage', 'image_url': 'https://images.unsplash.com/photo-1606293926075-69a00dbfde81?auto=format&fit=crop&w=1200&q=85', 'image': 'place-17', 'description': 'Historic ruins, stone landscapes, cycling and guided heritage walks.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Hampi, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Hampi, India', 'Day 3 · Food, culture and experiences around Hampi, India', 'Day 4 · Flexible nature, heritage or guided day trip in Hampi, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Australia: Coast, Wildlife & Cities', 'destination': 'Australia', 'days': '6 days / 5 nights', 'price': 139999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1506973035872-a4ec16b8e8d9?auto=format&fit=crop&w=1200&q=85', 'image': 'place-18', 'description': 'Coastal walks, wildlife experiences and vibrant city neighbourhoods.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Australia and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Australia', 'Day 3 · Food, culture and experiences around Australia', 'Day 4 · Flexible nature, heritage or guided day trip in Australia', 'Day 5 · Optional excursion and relaxed evening in Australia', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Meghalaya: Waterfalls & Living Roots', 'destination': 'Meghalaya, India', 'days': '5 days / 4 nights', 'price': 28999, 'style': 'Adventure', 'image_url': 'https://images.unsplash.com/photo-1441974231531-c6227db76e6?auto=format&fit=crop&w=1200&q=85', 'image': 'place-19', 'description': 'Waterfalls, forest paths, caves and living root bridge excursions.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Meghalaya, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Meghalaya, India', 'Day 3 · Food, culture and experiences around Meghalaya, India', 'Day 4 · Flexible nature, heritage or guided day trip in Meghalaya, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Nepal: Himalayan Trails & Heritage', 'destination': 'Nepal', 'days': '5 days / 4 nights', 'price': 54999, 'style': 'Adventure', 'image_url': 'https://images.unsplash.com/photo-1544735716-392fe2489ffa?auto=format&fit=crop&w=1200&q=85', 'image': 'place-20', 'description': 'Mountain scenery, cultural heritage and guided walking options.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Nepal and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Nepal', 'Day 3 · Food, culture and experiences around Nepal', 'Day 4 · Flexible nature, heritage or guided day trip in Nepal', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Varanasi: Riverfront & Living Heritage', 'destination': 'Varanasi, India', 'days': '6 days / 5 nights', 'price': 19999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1561361513-2d000a50f0dc?auto=format&fit=crop&w=1200&q=85', 'image': 'place-21', 'description': 'Riverfront traditions, historic lanes, craft markets and local food.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Varanasi, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Varanasi, India', 'Day 3 · Food, culture and experiences around Varanasi, India', 'Day 4 · Flexible nature, heritage or guided day trip in Varanasi, India', 'Day 5 · Optional excursion and relaxed evening in Varanasi, India', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Singapore: Gardens, Food & Skyline', 'destination': 'Singapore', 'days': '5 days / 4 nights', 'price': 89999, 'style': 'City & Food', 'image_url': 'https://images.unsplash.com/photo-1525625293386-3f8f99389edd?auto=format&fit=crop&w=1200&q=85', 'image': 'place-22', 'description': 'Gardens, neighbourhood food, waterfront walks and city architecture.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Singapore and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Singapore', 'Day 3 · Food, culture and experiences around Singapore', 'Day 4 · Flexible nature, heritage or guided day trip in Singapore', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Sikkim: Mountain Roads & Monasteries', 'destination': 'Sikkim, India', 'days': '5 days / 4 nights', 'price': 31999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1200&q=85', 'image': 'place-23', 'description': 'Mountain landscapes, monasteries, lakes and village trails.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Sikkim, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Sikkim, India', 'Day 3 · Food, culture and experiences around Sikkim, India', 'Day 4 · Flexible nature, heritage or guided day trip in Sikkim, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Portugal: Coast & Historic Streets', 'destination': 'Portugal', 'days': '6 days / 5 nights', 'price': 97999, 'style': 'Relaxed', 'image_url': 'https://images.unsplash.com/photo-1555881400-74d7acaacd8b?auto=format&fit=crop&w=1200&q=85', 'image': 'place-24', 'description': 'Historic quarters, coastal views, local food and transit-friendly days.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Portugal and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Portugal', 'Day 3 · Food, culture and experiences around Portugal', 'Day 4 · Flexible nature, heritage or guided day trip in Portugal', 'Day 5 · Optional excursion and relaxed evening in Portugal', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Mysuru: Palace, Markets & Gardens', 'destination': 'Mysuru, India', 'days': '5 days / 4 nights', 'price': 18999, 'style': 'Heritage', 'image_url': 'https://images.unsplash.com/photo-1566139884669-6a6c14fbe8c5?auto=format&fit=crop&w=1200&q=85', 'image': 'place-25', 'description': 'Palace architecture, markets, gardens and South Indian food.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Mysuru, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Mysuru, India', 'Day 3 · Food, culture and experiences around Mysuru, India', 'Day 4 · Flexible nature, heritage or guided day trip in Mysuru, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'South Africa: Coast & Wildlife', 'destination': 'South Africa', 'days': '5 days / 4 nights', 'price': 129999, 'style': 'Nature', 'image_url': 'https://images.unsplash.com/photo-1580060839134-75a5edca2e99?auto=format&fit=crop&w=1200&q=85', 'image': 'place-26', 'description': 'Coastal landscapes, wildlife excursions and cultural experiences.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in South Africa and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in South Africa', 'Day 3 · Food, culture and experiences around South Africa', 'Day 4 · Flexible nature, heritage or guided day trip in South Africa', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Kutch: White Desert & Craft Villages', 'destination': 'Kutch, India', 'days': '6 days / 5 nights', 'price': 25999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?auto=format&fit=crop&w=1200&q=85', 'image': 'place-27', 'description': 'Salt desert scenery, handicrafts, local food and village culture.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Kutch, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Kutch, India', 'Day 3 · Food, culture and experiences around Kutch, India', 'Day 4 · Flexible nature, heritage or guided day trip in Kutch, India', 'Day 5 · Optional excursion and relaxed evening in Kutch, India', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}, {'name': 'Türkiye: Heritage & Bazaar Trails', 'destination': 'Türkiye', 'days': '5 days / 4 nights', 'price': 89999, 'style': 'Culture', 'image_url': 'https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?auto=format&fit=crop&w=1200&q=85', 'image': 'place-28', 'description': 'Historic architecture, bazaars, waterfront views and regional cuisine.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Türkiye and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Türkiye', 'Day 3 · Food, culture and experiences around Türkiye', 'Day 4 · Flexible nature, heritage or guided day trip in Türkiye', 'Day 5 · Explore at your own pace and depart']}, {'name': 'Puducherry: Seafront & French Quarter', 'destination': 'Puducherry, India', 'days': '5 days / 4 nights', 'price': 17999, 'style': 'Relaxed', 'image_url': 'https://images.unsplash.com/photo-1494783367193-149034c05e8f?auto=format&fit=crop&w=1200&q=85', 'image': 'place-29', 'description': 'Seafront promenades, heritage streets, cafés and cycling routes.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in Puducherry, India and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in Puducherry, India', 'Day 3 · Food, culture and experiences around Puducherry, India', 'Day 4 · Flexible nature, heritage or guided day trip in Puducherry, India', 'Day 5 · Explore at your own pace and depart']}, {'name': 'New Zealand: Lakes & Outdoor Routes', 'destination': 'New Zealand', 'days': '6 days / 5 nights', 'price': 159999, 'style': 'Adventure', 'image_url': 'https://images.unsplash.com/photo-1469521669194-babb45599def?auto=format&fit=crop&w=1200&q=85', 'image': 'place-30', 'description': 'Scenic drives, lakes, short hikes and outdoor activities.', 'includes': ['Accommodation planning estimate', 'Local transportation allowance', 'Cultural or nature activities', 'Food and entry-fee allowance'], 'itinerary': ['Day 1 · Arrive in New Zealand and settle in', 'Day 2 · Explore signature sights and local neighbourhoods in New Zealand', 'Day 3 · Food, culture and experiences around New Zealand', 'Day 4 · Flexible nature, heritage or guided day trip in New Zealand', 'Day 5 · Optional excursion and relaxed evening in New Zealand', 'Day 5 · Explore at your own pace and depart', 'Day 6 · Departure']}]

@app.route('/stays', defaults={'catalog_name': 'stays'})
@app.route('/transportation', defaults={'catalog_name': 'transportation'})
@app.route('/activities', defaults={'catalog_name': 'activities'})
@app.route('/<catalog_name>')
def catalog(catalog_name):
    if catalog_name not in CATALOG:
        abort(404)
    data = CATALOG[catalog_name]
    available_trips = []
    user = current_user()
    if user:
        available_trips.extend(Trip.query.filter_by(creator_id=user.id).order_by(Trip.created_at.desc()).all())
        memberships = Membership.query.filter_by(user_id=user.id, status='accepted').all()
        known_ids = {trip.id for trip in available_trips}
        available_trips.extend(m.trip for m in memberships if m.trip and m.trip.id not in known_ids)
    return render_template('catalog.html', catalog_name=catalog_name, data=data, available_trips=available_trips)

@app.route('/packages')
def packages():
    return render_template('packages.html', packages=PACKAGES)

@app.route('/packages/<int:package_index>/start', methods=['POST'])
@login_required
def start_package(package_index):
    if package_index < 0 or package_index >= len(PACKAGES): abort(404)
    pack = PACKAGES[package_index]
    from datetime import timedelta
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=max(1, int(pack['days'].split()[0])-1))
    trip = Trip(title=pack['name'], destination=pack['destination'], start_location=current_user().city or 'Your city', start_date=start.isoformat(), end_date=end.isoformat(), budget=pack['price'], description=pack['description'] + ' Package costs are planning estimates, not bookings. You can edit every item after creating the trip.', interests=pack['style']+', sightseeing, photography', max_members=5, creator_id=current_user().id)
    db.session.add(trip); db.session.commit()
    for i, item in enumerate(pack['itinerary']):
        db.session.add(ItineraryItem(trip_id=trip.id, added_by=current_user().id, day=item.split(' · ')[0], title=item.split(' · ',1)[1], time='', notes='Suggested package itinerary — edit to fit your plans.', cost=0))
    for title, category, amount in [(pack['includes'][0], 'Accommodation', round(pack['price']*.30)), (pack['includes'][1], 'Transportation', round(pack['price']*.25)), (pack['includes'][2], 'Activities', round(pack['price']*.15)), (pack['includes'][3], 'Activities', round(pack['price']*.10))]:
        db.session.add(Expense(trip_id=trip.id, added_by=current_user().id, category=category, title=title, amount=amount, details='Package planning estimate — edit or remove as needed.'))
    db.session.commit()
    flash('Package added as your trip! You can edit the dates, itinerary and every estimated cost.', 'success')
    return redirect(url_for('trip_detail', trip_id=trip.id))

@app.route('/catalog/<catalog_name>/<int:item_index>/add', methods=['POST'])
@login_required
def add_catalog_item(catalog_name, item_index):
    if catalog_name not in CATALOG or item_index < 0 or item_index >= len(CATALOG[catalog_name]['items']): abort(404)
    try:
        trip_id = int(request.form.get('trip_id', ''))
    except (TypeError, ValueError):
        flash('Choose a trip before adding this item.', 'error')
        return redirect(url_for('catalog', catalog_name=catalog_name))
    trip = trip_access(trip_id)
    item = CATALOG[catalog_name]['items'][item_index]
    title = request.form.get('title', item['name']).strip()[:160] or item['name']
    try: amount = float(request.form.get('amount', item['price']))
    except ValueError: amount = item['price']
    if amount <= 0 or amount > 100000000:
        flash('Enter a valid amount.', 'error')
    else:
        db.session.add(Expense(trip_id=trip.id, added_by=current_user().id, category=CATALOG[catalog_name]['category'], title=title, amount=amount, details=f"{item['place']} · Editable estimate · {item['unit']}"))
        db.session.commit(); flash(f"{title} added to {trip.title}'s shared budget.", 'success')
    return redirect(url_for('trip_detail', trip_id=trip.id) + '#budget')

@app.route('/buddies/connect/<int:user_id>', methods=['POST'])
@login_required
def connect(user_id):
    me=current_user(); other=db.session.get(User,user_id)
    if not other or other.id==me.id: abort(404)
    existing=Connection.query.filter(or_(db.and_(Connection.sender_id==me.id,Connection.receiver_id==other.id),db.and_(Connection.sender_id==other.id,Connection.receiver_id==me.id))).first()
    if existing: flash('A connection request already exists.', 'info')
    else: db.session.add(Connection(sender_id=me.id,receiver_id=other.id)); db.session.commit(); flash('Connection request sent.', 'success')
    return redirect(url_for('buddies'))

@app.route('/connections')
@login_required
def connections():
    me=current_user(); incoming=Connection.query.filter_by(receiver_id=me.id,status='pending').all()
    outgoing=Connection.query.filter_by(sender_id=me.id,status='pending').all()
    accepted=Connection.query.filter(or_(db.and_(Connection.sender_id==me.id,Connection.status=='accepted'),db.and_(Connection.receiver_id==me.id,Connection.status=='accepted'))).all()
    return render_template('connections.html',incoming=incoming,outgoing=outgoing,accepted=accepted,me=me)

@app.route('/connections/<int:conn_id>/<action>', methods=['POST'])
@login_required
def connection_action(conn_id,action):
    c=db.session.get(Connection,conn_id)
    if not c or c.receiver_id!=current_user().id or c.status!='pending' or action not in ('accept','reject'): abort(403)
    c.status='accepted' if action=='accept' else 'rejected'; db.session.commit(); flash('Connection request updated.', 'success'); return redirect(url_for('connections'))

@app.route('/messages', defaults={'other_id': None})
@app.route('/messages/<int:other_id>')
@login_required
def messages(other_id):
    me=current_user(); people=[]
    accepted=Connection.query.filter(or_(db.and_(Connection.sender_id==me.id,Connection.status=='accepted'),db.and_(Connection.receiver_id==me.id,Connection.status=='accepted'))).all()
    ids=set()
    for c in accepted: ids.add(c.receiver_id if c.sender_id==me.id else c.sender_id)
    shared=Membership.query.filter_by(user_id=me.id,status='accepted').all()
    for m in shared:
        trip=m.trip
        ids.update(x.user_id for x in trip.memberships if x.status=='accepted' and x.user_id!=me.id)
        ids.add(trip.creator_id)
    ids.discard(me.id)
    people=User.query.filter(User.id.in_(ids)).all() if ids else []
    other=db.session.get(User,other_id) if other_id else (people[0] if people else None)
    if other and other.id not in ids: abort(403)
    chat=[]
    if other:
        chat=Message.query.filter(or_(db.and_(Message.sender_id==me.id,Message.receiver_id==other.id),db.and_(Message.sender_id==other.id,Message.receiver_id==me.id))).order_by(Message.created_at.asc()).all()
    return render_template('messages.html',people=people,other=other,chat=chat,me=me)

@app.route('/api/v1/messages/<int:other_id>', methods=['POST'])
@login_required
def api_send_message(other_id):
    me=current_user(); other=db.session.get(User,other_id)
    if not other or other.id==me.id: return jsonify(error='Invalid recipient.'),400
    connected=Connection.query.filter(or_(db.and_(Connection.sender_id==me.id,Connection.receiver_id==other.id),db.and_(Connection.sender_id==other.id,Connection.receiver_id==me.id))).filter_by(status='accepted').first()
    shared=False
    for membership in Membership.query.filter_by(user_id=me.id,status='accepted').all():
        if membership.trip.creator_id==other.id or Membership.query.filter_by(trip_id=membership.trip_id,user_id=other.id,status='accepted').first(): shared=True; break
    if not connected and not shared: return jsonify(error='Connect first or share an accepted trip to message.'),403
    body=(request.json or {}).get('body','').strip()
    if not body or len(body)>500: return jsonify(error='Message must be between 1 and 500 characters.'),400
    # Keep trip coordination in the app: block common off-platform contact details and links.
    contact_patterns = [
        r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',
        r'(?i)https?://|www\.',
        r'(?i)\b(?:instagram|snapchat|telegram|whatsapp|discord|facebook)\s*(?:id|username|handle)?\s*[:@-]',
        r'(?<!\w)(?:\+?\d[\d .()/-]{8,}\d)(?!\w)',
        r'(?i)\b(?:dm me|text me|call me|message me on|add me on)\b',
        r'(?<!\w)@[A-Za-z0-9_.]{3,}'
    ]
    if any(re.search(pattern, body) for pattern in contact_patterns):
        return jsonify(error='For safety, keep coordination here. Phone numbers, emails, social handles and external links are not allowed in chat.'),400
    recent_count = Message.query.filter_by(sender_id=me.id, receiver_id=other.id).filter(Message.created_at >= datetime.utcnow()-timedelta(minutes=1)).count()
    if recent_count >= 10:
        return jsonify(error='Please slow down: you can send up to 10 messages per minute to one person.'),429
    msg=Message(sender_id=me.id,receiver_id=other.id,body=body); db.session.add(msg); db.session.commit()
    return jsonify(id=msg.id,body=msg.body,sender_id=me.id,created_at=msg.created_at.isoformat()),201

QUIZZES = {
    'travel-safety': {
        'title': 'Travel Safety Basics', 'description': 'Build safer travel habits before you go.',
        'questions': [
            {'q':'What should you do before meeting a new travel buddy in person?', 'options':['Meet in a public place and tell someone your plan','Share your home address','Hand over your passport'], 'answer':0},
            {'q':'Where should you keep a copy of important travel documents?', 'options':['Only in an unlocked public folder','Securely, separate from the originals','Post it publicly'], 'answer':1},
            {'q':'What is the safest response to a suspicious booking link?', 'options':['Open it quickly','Share it with everyone','Verify the source before opening'], 'answer':2},
            {'q':'What should group members agree on before a trip?', 'options':['Budget, dates and expectations','Nothing until arrival','Only who takes photos'], 'answer':0},
            {'q':'If a travel plan makes you uncomfortable, you should…', 'options':['Ignore your concern','Speak up and use reporting/support options','Feel forced to continue'], 'answer':1},
        ]
    },
    'responsible-travel': {
        'title': 'Responsible Travel', 'description': 'Learn how to travel thoughtfully and respectfully.',
        'questions': [
            {'q':'What is a good way to support a local community?', 'options':['Respect local customs and use local businesses','Ignore local rules','Leave rubbish behind'], 'answer':0},
            {'q':'How should you behave at a cultural or religious site?', 'options':['Disregard signs','Follow site guidance and dress expectations','Take photos where prohibited'], 'answer':1},
            {'q':'Which choice reduces waste while travelling?', 'options':['Use a reusable bottle where safe','Use a new disposable bottle every hour','Leave packaging outdoors'], 'answer':0},
            {'q':'How should wildlife experiences be chosen?', 'options':['Choose any attraction','Prefer ethical operators that avoid disturbing wildlife','Feed wild animals for photos'], 'answer':1},
            {'q':'What is a considerate group-trip habit?', 'options':['Agree on shared costs and plans clearly','Assume one person will pay everything','Change plans without telling anyone'], 'answer':0},
        ]
    }
}

@app.route('/quizzes')
@login_required
def quizzes():
    attempts = {a.quiz_key:a for a in QuizAttempt.query.filter_by(user_id=current_user().id).all()}
    points_earned = db.session.query(db.func.coalesce(db.func.sum(QuizAttempt.points_awarded), 0)).filter_by(user_id=current_user().id).scalar() or 0
    points_spent = db.session.query(db.func.coalesce(db.func.sum(CouponRedemption.points_cost), 0)).filter_by(user_id=current_user().id).scalar() or 0
    coupons = CouponRedemption.query.filter_by(user_id=current_user().id).order_by(CouponRedemption.created_at.desc()).all()
    return render_template('quizzes.html', quizzes=QUIZZES, attempts=attempts, points=max(0,points_earned-points_spent), coupons=coupons)

@app.route('/quizzes/<quiz_key>', methods=['GET','POST'])
@login_required
def take_quiz(quiz_key):
    quiz = QUIZZES.get(quiz_key)
    if not quiz: abort(404)
    user = current_user()
    existing = QuizAttempt.query.filter_by(user_id=user.id, quiz_key=quiz_key).first()
    if request.method == 'POST':
        if existing:
            flash('You have already completed this quiz. Each quiz can earn points once.', 'info')
            return redirect(url_for('quizzes'))
        score = 0
        for index, question in enumerate(quiz['questions']):
            try: selected = int(request.form.get(f'q{index}', '-1'))
            except ValueError: selected = -1
            if selected == question['answer']: score += 1
        points_awarded = score * 10
        db.session.add(QuizAttempt(user_id=user.id, quiz_key=quiz_key, score=score, total=len(quiz['questions']), points_awarded=points_awarded))
        db.session.commit()
        flash(f'Quiz complete: {score}/{len(quiz["questions"])} correct. You earned {points_awarded} points.', 'success')
        return redirect(url_for('quizzes'))
    if existing:
        flash('This quiz has already been completed on your account.', 'info')
        return redirect(url_for('quizzes'))
    return render_template('quiz_take.html', quiz=quiz, quiz_key=quiz_key)

@app.route('/rewards/redeem', methods=['POST'])
@login_required
def redeem_reward():
    user=current_user()
    earned = db.session.query(db.func.coalesce(db.func.sum(QuizAttempt.points_awarded), 0)).filter_by(user_id=user.id).scalar() or 0
    spent = db.session.query(db.func.coalesce(db.func.sum(CouponRedemption.points_cost), 0)).filter_by(user_id=user.id).scalar() or 0
    if earned-spent < 100:
        flash('You need 100 available points to redeem a reward.', 'error')
    else:
        code='TBF-'+secrets.token_hex(4).upper()
        db.session.add(CouponRedemption(user_id=user.id, code=code, points_cost=100))
        db.session.commit()
        flash(f'Your demo reward code is {code}. It is a prototype coupon and is not a live merchant discount.', 'success')
    return redirect(url_for('quizzes'))

@app.route('/admin/verifications')
@login_required
def admin_verifications():
    admin_email=os.getenv('ADMIN_EMAIL','').strip().lower()
    if not admin_email or current_user().email.lower() != admin_email:
        abort(403)
    items=VerificationRequest.query.order_by(VerificationRequest.created_at.desc()).all()
    return render_template('admin_verifications.html', items=items)

@app.route('/admin/verifications/<int:request_id>/<action>', methods=['POST'])
@login_required
def review_verification(request_id, action):
    admin_email=os.getenv('ADMIN_EMAIL','').strip().lower()
    if not admin_email or current_user().email.lower() != admin_email:
        abort(403)
    item=db.session.get(VerificationRequest,request_id)
    if not item: abort(404)
    if action not in {'verify','reject'}: abort(400)
    item.status='verified' if action=='verify' else 'rejected'
    item.reviewed_at=datetime.utcnow(); item.reviewer_id=current_user().id
    db.session.commit()
    flash('Verification status updated. Only mark verified after a genuine, authorised check.', 'success')
    return redirect(url_for('admin_verifications'))

@app.route('/api/v1/trips/<int:trip_id>/budget')
def api_budget(trip_id):
    trip=db.session.get(Trip,trip_id)
    if not trip: return jsonify(error='Trip not found.'),404
    cats=expense_totals(trip); total=sum(cats.values())
    return jsonify(trip_id=trip.id,categories=cats,total=total,per_person=round(total/(1+len([m for m in trip.memberships if m.status=='accepted'])),2))

@app.errorhandler(403)
def forbidden(_): return render_template('error.html', code=403, message='You do not have permission to view this page.'),403
@app.errorhandler(404)
def not_found(_): return render_template('error.html', code=404, message='We could not find that page.'),404

with app.app_context():
    db.create_all()
    # Add demo records only when missing. These are ordinary database rows, not hardcoded UI cards.
    demo_people = [
        ('Aarav Mehta','aarav@example.com','Delhi','Mountains, local food and long road trips.','Hiking,Photography,Food','Adventure',18000),
        ('Sana Kapoor','sana@example.com','Jaipur','Slow travel, culture and beautiful sunsets.','Culture,Photography,Food','Relaxed',15000),
        ('Riya Sharma','riya@example.com','Noida','Weekend explorer who loves cafes and hidden streets.','Food,Photography,Culture','Flexible',12000),
        ('Kabir Singh','kabir@example.com','Lucknow','Here for road trips, hikes and spontaneous plans.','Hiking,Adventure,Nature','Adventure',22000),
        ('Meera Nair','meera@example.com','Kochi','Nature, beaches, books and slow mornings.','Nature,Beaches,Photography','Relaxed',16000),
        ('Dev Malhotra','dev@example.com','Chandigarh','Budget-conscious traveller and mountain lover.','Hiking,Camping,Adventure','Budget',14000),
        ('Ananya Verma','ananya@example.com','Delhi','I plan the basics and leave room for surprises.','Culture,Food,Shopping','Flexible',18000),
        ('Ishaan Rao','ishaan@example.com','Pune','Photographer looking for scenic routes.','Photography,Nature,Road trips','Adventure',26000),
        ('Zoya Khan','zoya@example.com','Mumbai','Beaches, music, art walks and good food.','Beaches,Music,Food','Relaxed',20000),
        ('Arjun Das','arjun@example.com','Kolkata','History buff who loves meeting new people.','Culture,History,Food','Culture',13000),
        ('Tanya Gupta','tanya@example.com','Ghaziabad','Short trips, cute stays and travel reels.','Photography,Shopping,Cafes','Flexible',10000),
        ('Vihaan Joshi','vihaan@example.com','Indore','Adventure sports and early morning hikes.','Adventure,Hiking,Nature','Adventure',24000),
        ('Naina Roy','naina@example.com','Bengaluru','Remote worker collecting weekend escapes.','Nature,Cafes,Photography','Budget',17000),
        ('Rehan Ali','rehan@example.com','Hyderabad','Food trails and local culture first.','Food,Culture,History','Culture',15000),
        ('Pooja Menon','pooja@example.com','Chennai','Ocean person, wildlife fan and planner.','Beaches,Nature,Wildlife','Relaxed',19000),
        ('Aditya Jain','aditya@example.com','Agra','Looking for friendly groups and new routes.','Road trips,Adventure,Food','Budget',11000),
    ]
    demo_people.extend([
        ('Isha Khanna','isha@example.com','Delhi','Solo traveller who loves museums, markets and thoughtful itineraries.','Culture,Food,Photography','Culture',22000),
        ('Kavya Iyer','kavya@example.com','Bengaluru','Weekend hiker looking for friendly groups and green escapes.','Hiking,Nature,Camping','Adventure',18000),
        ('Maya Fernandes','maya@example.com','Goa','Beach lover who enjoys local food and slow travel.','Beaches,Food,Swimming','Relaxed',24000),
        ('Elena Martin','elena@example.com','Barcelona, Spain','Architecture, art and long city walks are my thing.','Art,Architecture,Food','Culture',95000),
        ('Aisha Rahman','aisha@example.com','Kuala Lumpur, Malaysia','I love street food, train journeys and meeting new people.','Food,Culture,Photography','Flexible',70000),
        ('Lucia Costa','lucia@example.com','Lisbon, Portugal','Coastal day trips, music and hidden cafés.','Music,Beaches,Cafes','Relaxed',90000),
        ('Yuna Sato','yuna@example.com','Osaka, Japan','Food markets, gardens and easygoing travel days.','Food,Culture,Shopping','Flexible',85000),
        ('Tara Bansal','tara@example.com','Jaipur','Heritage stays, craft markets and colourful streets.','Culture,Shopping,Photography','Culture',16000),
        ('Noor Siddiqui','noor@example.com','Hyderabad','A curious traveller who plans around food and history.','Food,History,Culture','Budget',14000),
        ('Kiara Dsouza','kiara@example.com','Mumbai','Ocean swims, concerts and spontaneous road trips.','Beaches,Music,Road trips','Adventure',26000),
        ('Priya Shah','priya@example.com','Ahmedabad','Interested in sustainable travel and local experiences.','Nature,Culture,Food','Relaxed',19000),
        ('Chloe Bennett','chloe@example.com','London, United Kingdom','I enjoy neighbourhood walks, galleries and train travel.','Art,History,Photography','Culture',120000),
        ('Fatima Ali','fatima@example.com','Dubai, UAE','Desert experiences, city architecture and food tours.','Architecture,Food,Adventure','Flexible',100000),
        ('Neel Kapoor','neel@example.com','Pune','Cycling, trekking and budget-friendly group trips.','Cycling,Hiking,Nature','Adventure',18000),
        ('Rohan Das','rohan@example.com','Kolkata','Photographer looking for new landscapes and local stories.','Photography,History,Food','Culture',20000),
        ('Mateo Ruiz','mateo@example.com','Rome, Italy','I love food walks, old towns and scenic rail routes.','Food,History,Trains','Relaxed',105000),
        ('Liam Parker','liam@example.com','Vancouver, Canada','Nature trails and city coffee stops in equal measure.','Nature,Hiking,Cafes','Adventure',130000),
        ('Daniel Kim','daniel@example.com','Seoul, South Korea','K-pop, street food and exploring beyond tourist areas.','Music,Food,Shopping','Flexible',100000),
        ('Kenji Mori','kenji@example.com','Tokyo, Japan','Early riser for quiet temples and photography walks.','Photography,Culture,Nature','Budget',82000),
        ('Omar Hassan','omar@example.com','Cairo, Egypt','History, architecture and local markets.','History,Architecture,Food','Culture',90000),
        ('Leo Martin','leo@example.com','Paris, France','Cycling, museums and discovering small neighbourhoods.','Cycling,Art,Culture','Flexible',115000),
        ('Sam Wilson','sam@example.com','Sydney, Australia','Coastal hikes, beaches and relaxed group travel.','Beaches,Hiking,Nature','Adventure',140000),
        ('Ethan Cole','ethan@example.com','New York, USA','City breaks, live music and trying new food.','Music,Food,City walks','Flexible',125000),
        ('Amir Khan','amir@example.com','Kathmandu, Nepal','Mountain trails and community-based travel.','Hiking,Nature,Culture','Adventure',55000),
    ])
    people = {}
    for name,email,city,bio,interests,style,budget in demo_people:
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(name=name,email=email,password_hash=generate_password_hash('Travel123!'),city=city,bio=bio,interests=interests,travel_style=style,budget=budget)
            db.session.add(user); db.session.flush()
        people[email] = user
    db.session.commit()
    trip_specs = [
      ('Himalayan Escape','India','Delhi','2027-06-10','2027-06-17',25000,'High mountain passes, blue lakes, monasteries and unforgettable road-trip views.','Hiking,Photography,Adventure','aarav@example.com',5),
      ('Goa Beach & Cafe Crawl','India','Mumbai','2027-01-15','2027-01-19',14000,'Beach sunsets, local cafes, heritage lanes and relaxed mornings.','Beaches,Food,Photography','zoya@example.com',6),
      ('Kerala Backwater Slow Trip','India','Kochi','2027-02-08','2027-02-13',18500,'Green hills, backwaters, local food and a little time to slow down.','Nature,Food,Photography','meera@example.com',5),
      ('Jaipur Heritage Weekend','India','Delhi','2027-01-22','2027-01-25',9000,'Forts, bazaars, heritage architecture and local food stops.','Culture,History,Food','sana@example.com',5),
      ('Rishikesh Adventure Days','India','Ghaziabad','2027-03-12','2027-03-15',10500,'Riverside cafes, forest walks and optional guided rafting.','Adventure,Nature,Hiking','kabir@example.com',6),
      ('Manali Snow & Trails','India','Chandigarh','2027-02-18','2027-02-22',16000,'Pine forests, mountain views and flexible outdoor days.','Hiking,Photography,Adventure','dev@example.com',5),
      ('Udaipur Lakeside Escape','India','Jaipur','2027-02-04','2027-02-07',11500,'Lake views, old-city walks, art and evening boat rides.','Culture,Photography,Food','ananya@example.com',4),
      ('Meghalaya Cloud Trails','India','Guwahati','2027-04-10','2027-04-16',23000,'Waterfalls, living root bridges and misty green landscapes.','Nature,Hiking,Photography','ishaan@example.com',5),
      ('Mumbai Arts & Food Weekend','Mumbai','Pune','2027-01-29','2027-02-01',12500,'Street food, galleries, seaside walks and city photography.','Food,Art,Photography','riya@example.com',6),
      ('Andaman Blue Escape','Andaman','Port Blair','2027-03-05','2027-03-10',28500,'Clear water, island time, snorkelling and relaxed beach days.','Beaches,Nature,Adventure','pooja@example.com',5),
      ('Varanasi Culture Walk','Varanasi','Lucknow','2027-02-26','2027-03-01',8500,'A thoughtful trip for riverfront walks, food and local heritage.','Culture,History,Food','arjun@example.com',4),
      ('Coorg Green Weekend','Coorg','Bengaluru','2027-04-02','2027-04-05',13000,'Coffee estates, forest roads and slow mornings in the hills.','Nature,Food,Road trips','naina@example.com',5),
      ('Spiti Valley Road Trip','Spiti Valley','Chandigarh','2027-06-20','2027-06-27',27000,'Remote villages, mountain roads and starry skies.','Road trips,Adventure,Photography','vihaan@example.com',5),
      ('Agra & Fatehpur Sikri','Agra','Delhi','2027-01-08','2027-01-10',6500,'Architecture, history, local breakfast spots and sunrise views.','History,Culture,Photography','aditya@example.com',6),
      ('Pondicherry Slow Living','Pondicherry','Chennai','2027-03-19','2027-03-23',15500,'Coastal cycling, colourful streets, cafes and beach time.','Beaches,Cafes,Photography','tanya@example.com',5),
      ('Tokyo Neon & Food Trails','Japan','Delhi','2027-05-08','2027-05-14',95000,'Explore Shibuya, quiet gardens, neighbourhood food spots and the city after dark.','Food,Culture,Photography','aarav@example.com',5),
      ('Kyoto Temples & Traditions','Kyoto, Japan','Japan','2027-05-15','2027-05-19',72000,'A slower journey through temple paths, traditional streets, gardens and tea culture.','Culture,History,Photography','sana@example.com',5),
      ('Bali Beaches & Rice Terraces','Indonesia','Delhi','2027-06-02','2027-06-08',68000,'Beach sunsets, Ubud rice terraces, local markets and optional beginner surf lessons.','Beaches,Nature,Food','zoya@example.com',6),
      ('Paris Art & Café Walks','France','Delhi','2027-04-12','2027-04-17',110000,'Museums, riverside walks, neighbourhood cafés and iconic architecture.','Art,Culture,Food','riya@example.com',5),
      ('Lisbon Coast & Old Town','Portugal','Delhi','2027-05-20','2027-05-25',98000,'Tram rides, tiled streets, viewpoints, coastal day trips and local food.','Culture,Food,Photography','ananya@example.com',5),
      ('Swiss Alps Scenic Escape','Switzerland','Zurich','2027-07-06','2027-07-11',145000,'Mountain viewpoints, lake walks and scenic train journeys through the Alps.','Hiking,Nature,Photography','ishaan@example.com',5),
      ('Bangkok Street Food & Canals','Thailand','Delhi','2027-03-08','2027-03-13',62000,'Street-food discoveries, temple visits, river ferries and colourful markets.','Food,Culture,Shopping','rehan@example.com',6),
      ('Istanbul Between Continents','Türkiye','Delhi','2027-04-22','2027-04-27',85000,'Historic neighbourhoods, bazaars, waterfront walks and local food stops.','History,Culture,Food','arjun@example.com',5),
      ('Cape Town Coast & Nature','South Africa','Johannesburg','2027-09-10','2027-09-16',125000,'Coastal viewpoints, city neighbourhoods, botanical gardens and guided nature outings.','Nature,Photography,Adventure','meera@example.com',5),
      ('Singapore City Discovery','Singapore','Delhi','2027-08-04','2027-08-08',88000,'Gardens, waterfront architecture, hawker centres and efficient city transit.','Food,Architecture,Photography','dev@example.com',5),
      ('Sydney Harbour & Beaches','Australia','Delhi','2027-11-02','2027-11-08',138000,'Harbour walks, coastal paths, city neighbourhoods and beach time.','Beaches,Nature,Photography','pooja@example.com',5),
      ('Mysuru Palace & Coffee Trails','Mysuru, India','Bengaluru','2027-04-12','2027-04-15',12500,'Palace architecture, local markets, gardens and a day trip into the coffee-growing hills.','Culture,Food,Photography','tara@example.com',5),
      ('Rome Food & Ancient Streets','Italy','Delhi','2027-05-05','2027-05-10',112000,'Ancient landmarks, piazzas, neighbourhood trattorias and relaxed evening walks.','History,Food,Architecture','mateo@example.com',5),
      ('Darjeeling Toy Train Escape','Darjeeling, India','Siliguri','2027-04-18','2027-04-22',17500,'Tea gardens, mountain viewpoints, local markets and a scenic heritage train ride.','Nature,Trains,Photography','neel@example.com',5),
      ('Barcelona Art & Coast','Spain','Delhi','2027-06-10','2027-06-15',108000,'Distinctive architecture, tapas stops, art museums and Mediterranean waterfront walks.','Art,Food,Beaches','elena@example.com',5),
      ('Hampi Heritage Backpacking','Hampi, India','Bengaluru','2027-02-11','2027-02-15',14500,'Ancient ruins, boulder landscapes, sunrise viewpoints and easygoing café stops.','History,Photography,Adventure','rohan@example.com',5),
      ('London Neighbourhood Week','United Kingdom','Delhi','2027-07-12','2027-07-17',132000,'Museums, markets, riverside walks, neighbourhood cafés and day-trip options.','History,Art,Food','chloe@example.com',5),
      ('Sikkim Lakes & Monasteries','Sikkim, India','Bagdogra','2027-05-10','2027-05-16',24500,'Mountain roads, monasteries, alpine lakes and local food in the eastern Himalayas.','Nature,Culture,Hiking','kavya@example.com',5),
      ('Dubai Skyline & Desert','Dubai, UAE','Delhi','2027-03-14','2027-03-19',99000,'Architecture, old souks, waterfront evenings and an optional guided desert outing.','Architecture,Food,Photography','fatima@example.com',5),
      ('Puducherry Coastal Cycling','Puducherry, India','Chennai','2027-04-20','2027-04-24',16000,'Colourful lanes, coastal cycling, cafés and relaxed beach time.','Cycling,Beaches,Cafes','kiara@example.com',5),
      ('Seoul Street Food & Culture','South Korea','Delhi','2027-10-02','2027-10-07',102000,'Markets, palaces, neighbourhood food, riverside walks and contemporary culture.','Food,Culture,Music','daniel@example.com',5),
      ('Kutch White Desert & Crafts','Kutch, India','Ahmedabad','2027-01-18','2027-01-23',21000,'White desert landscapes, craft villages, local textiles and starry evenings.','Culture,Photography,Nature','priya@example.com',5),
      ('Kathmandu Valley & Foothills','Nepal','Delhi','2027-09-05','2027-09-10',59000,'Historic squares, temples, local food and scenic foothill walks.','History,Hiking,Culture','amir@example.com',5),
      ('Orchha Forts & Riverside','Orchha, India','Jhansi','2027-02-08','2027-02-11',9500,'Historic palaces, riverside sunsets, quiet lanes and guided heritage walks.','History,Photography,Culture','noor@example.com',4),
      ('Maldives Island Reset','Maldives','Delhi','2027-11-10','2027-11-15',155000,'Island hopping, clear-water snorkelling, beach time and slow mornings.','Beaches,Nature,Swimming','maya@example.com',5),
      ('Ziro Valley Music & Nature','Ziro Valley, India','Guwahati','2027-09-20','2027-09-25',26000,'Green valley walks, village experiences, rice fields and regional food.','Music,Nature,Culture','isha@example.com',5),
      ('Prague Old Town & River','Prague, Czech Republic','Delhi','2027-08-15','2027-08-20',99000,'Old-town lanes, river views, architecture and cafés with a relaxed pace.','Architecture,History,Photography','leo@example.com',5),
      ('Lakshadweep Lagoon Days','Lakshadweep, India','Kochi','2027-03-22','2027-03-27',34000,'Turquoise lagoons, reef-safe water activities and peaceful island scenery.','Beaches,Nature,Swimming','pooja@example.com',5),
      ('Vienna Music & Museums','Vienna, Austria','Delhi','2027-10-12','2027-10-17',118000,'Historic cafés, museums, architecture and classical music experiences.','Music,Art,History','lucia@example.com',5),
      ('Jodhpur Blue City Weekend','Jodhpur, India','India','2027-02-19','2027-02-22',11000,'Blue lanes, fort viewpoints, bustling bazaars and local Rajasthani food.','Culture,Food,Photography','sana@example.com',5),
      ('Vancouver Trails & Waterfront','Canada','Delhi','2027-08-01','2027-08-07',145000,'Coastal paths, forest trails, waterfront neighbourhoods and coffee stops.','Nature,Hiking,Cafes','liam@example.com',5),
    ]
    for title,dest,origin,start,end,budget,desc,interests,email,cap in trip_specs:
        trip = Trip.query.filter_by(title=title,creator_id=people[email].id).first()
        if not trip:
            trip = Trip(title=title,destination=dest,start_location=origin,start_date=start,end_date=end,budget=budget,description=desc,interests=interests,max_members=cap,creator_id=people[email].id,status='open')
            db.session.add(trip); db.session.flush()
            # Starter itinerary and cost estimates make trip details useful immediately.
            db.session.add_all([
              ItineraryItem(trip_id=trip.id,added_by=trip.creator_id,day='Day 1',title=f'Arrive in {dest} and settle in',notes='Suggested plan — edit to suit the group.',cost=0),
              ItineraryItem(trip_id=trip.id,added_by=trip.creator_id,day='Day 2',title=f'Explore local highlights in {dest}',notes='Group can choose the exact stops together.',cost=0),
              Expense(trip_id=trip.id,added_by=trip.creator_id,category='Accommodation',title='Stay estimate',amount=round(budget*.28),details='Illustrative planning estimate; not a booking.'),
              Expense(trip_id=trip.id,added_by=trip.creator_id,category='Transportation',title='Local transport estimate',amount=round(budget*.24),details='Illustrative planning estimate; not a live fare.'),
              Expense(trip_id=trip.id,added_by=trip.creator_id,category='Activities',title='Sightseeing and activities estimate',amount=round(budget*.16),details='Illustrative planning estimate; editable by trip members.'),
            ])
    db.session.commit()

if __name__=='__main__':
    app.run(debug=os.getenv('FLASK_DEBUG','0')=='1')
