# app.py
import os
import datetime
import uuid
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Restaurant(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String, nullable=False)
    cuisine = db.Column(db.String, nullable=True)

class MenuItem(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    restaurant_id = db.Column(db.String, db.ForeignKey("restaurant.id"), nullable=False)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=True)
    price = db.Column(db.Float, nullable=False)
    available = db.Column(db.Boolean, default=True)

class Order(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String, db.ForeignKey("user.id"), nullable=False)
    restaurant_id = db.Column(db.String, db.ForeignKey("restaurant.id"), nullable=False)
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String, default="placed")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class OrderLine(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = db.Column(db.String, db.ForeignKey("order.id"), nullable=False)
    item_id = db.Column(db.String, db.ForeignKey("menu_item.id"), nullable=False)
    qty = db.Column(db.Integer, default=1)
    price = db.Column(db.Float, nullable=False)

# --- Helpers ---
def user_to_dict(u):
    return {"id": u.id, "name": u.name, "email": u.email, "created_at": u.created_at.isoformat()}

def menu_item_to_dict(m):
    return {"id": m.id, "restaurant_id": m.restaurant_id, "name": m.name, "description": m.description, "price": m.price, "available": m.available}

# --- Routes ---
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# Auth: signup
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json or {}
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    if not (name and email and password):
        return jsonify({"error": "name, email, password required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already exists"}), 400
    u = User(name=name, email=email, password_hash=generate_password_hash(password))
    db.session.add(u); db.session.commit()
    return jsonify({"message": "user created", "user": user_to_dict(u)}), 201

# Auth: login (returns simple token)
TOKENS = {}
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email"); password = data.get("password")
    if not (email and password):
        return jsonify({"error": "email and password required"}), 400
    u = User.query.filter_by(email=email).first()
    if not u or not check_password_hash(u.password_hash, password):
        return jsonify({"error": "invalid credentials"}), 401
    token = str(uuid.uuid4())
    TOKENS[token] = u.id
    return jsonify({"token": token, "user": user_to_dict(u)})

def auth_required(fn):
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token or token not in TOKENS:
            return jsonify({"error": "unauthorized"}), 401
        request.user_id = TOKENS[token]
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

# Restaurants & menu
@app.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    rs = Restaurant.query.all()
    return jsonify([{"id": r.id, "name": r.name, "cuisine": r.cuisine} for r in rs])

@app.route("/api/restaurants/<rid>/menu", methods=["GET"])
def restaurant_menu(rid):
    items = MenuItem.query.filter_by(restaurant_id=rid).all()
    return jsonify([menu_item_to_dict(i) for i in items])

# Place order (mock payment)
@app.route("/api/orders", methods=["POST"])
@auth_required
def place_order():
    data = request.json or {}
    restaurant_id = data.get("restaurant_id")
    items = data.get("items") or []
    if not restaurant_id or not items:
        return jsonify({"error": "restaurant_id and items required"}), 400
    total = 0.0
    for it in items:
        mi = MenuItem.query.get(it["item_id"])
        if not mi or not mi.available:
            return jsonify({"error": f"item {it.get('item_id')} not available"}), 400
        total += mi.price * int(it.get("qty", 1))
    order = Order(user_id=request.user_id, restaurant_id=restaurant_id, total=total, status="placed")
    db.session.add(order); db.session.commit()
    for it in items:
        mi = MenuItem.query.get(it["item_id"])
        ol = OrderLine(order_id=order.id, item_id=mi.id, qty=int(it.get("qty", 1)), price=mi.price)
        db.session.add(ol)
    db.session.commit()
    return jsonify({"message": "order placed", "order_id": order.id, "status": order.status}), 201

# Order tracking
@app.route("/api/orders/<oid>", methods=["GET"])
@auth_required
def get_order(oid):
    o = Order.query.get(oid)
    if not o or o.user_id != request.user_id:
        return jsonify({"error": "not found"}), 404
    lines = OrderLine.query.filter_by(order_id=o.id).all()
    return jsonify({
        "id": o.id,
        "restaurant_id": o.restaurant_id,
        "total": o.total,
        "status": o.status,
        "created_at": o.created_at.isoformat(),
        "items": [{"item_id": l.item_id, "qty": l.qty, "price": l.price} for l in lines]
    })

# Admin: update order status (simple)
@app.route("/api/admin/orders/<oid>/status", methods=["POST"])
def admin_update_status(oid):
    data = request.json or {}
    status = data.get("status")
    if status not in ("placed", "preparing", "out_for_delivery", "delivered"):
        return jsonify({"error": "invalid status"}), 400
    o = Order.query.get(oid)
    if not o:
        return jsonify({"error": "order not found"}), 404
    o.status = status
    db.session.commit()
    return jsonify({"message": "status updated", "order_id": o.id, "status": o.status})

# Recommendation: top-5 popular items (popularity baseline)
@app.route("/api/recommendations/top", methods=["GET"])
@auth_required
def top_recommendations():
    rows = db.session.query(OrderLine.item_id, db.func.sum(OrderLine.qty).label("count"))\
        .join(Order, Order.id == OrderLine.order_id)\
        .group_by(OrderLine.item_id).order_by(db.desc("count")).limit(5).all()
    result = []
    for item_id, cnt in rows:
        mi = MenuItem.query.get(item_id)
        if mi:
            result.append({"item": menu_item_to_dict(mi), "score": int(cnt)})
    return jsonify(result)

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# --- DB seed with restaurants and items ---
def seed():
    db.create_all()
    if Restaurant.query.count() > 0:
        return

    # Restaurants
    r1 = Restaurant(name="Spice Corner", cuisine="Indian")
    r2 = Restaurant(name="Pizza Planet", cuisine="Italian")
    r3 = Restaurant(name="Sushi House", cuisine="Japanese")
    r4 = Restaurant(name="Green Bowl", cuisine="Healthy")
    r5 = Restaurant(name="Burger Barn", cuisine="Fast Food")
    r6 = Restaurant(name="Taco Fiesta", cuisine="Mexican")
    db.session.add_all([r1, r2, r3, r4, r5, r6]); db.session.commit()

    # Menu items for Spice Corner (expanded)
    m1 = MenuItem(restaurant_id=r1.id, name="Butter Chicken", description="Creamy tomato gravy", price=200.0)
    m2 = MenuItem(restaurant_id=r1.id, name="Paneer Tikka", description="Grilled cottage cheese", price=150.0)
    m3 = MenuItem(restaurant_id=r1.id, name="Garlic Naan", description="Soft flatbread", price=40.0)
    m4 = MenuItem(restaurant_id=r1.id, name="Biryani (Chicken)", description="Aromatic rice", price=220.0)
    m20 = MenuItem(restaurant_id=r1.id, name="Chole Bhature", description="Spicy chickpeas with fried bread", price=160.0)
    m21 = MenuItem(restaurant_id=r1.id, name="Aloo Paratha", description="Stuffed potato flatbread", price=90.0)
    m22 = MenuItem(restaurant_id=r1.id, name="Raita", description="Cooling yogurt side", price=30.0)

    # Pizza Planet (expanded)
    m5 = MenuItem(restaurant_id=r2.id, name="Margherita", description="Classic cheese pizza", price=250.0)
    m6 = MenuItem(restaurant_id=r2.id, name="Pepperoni", description="Pepperoni pizza", price=300.0)
    m7 = MenuItem(restaurant_id=r2.id, name="Garlic Bread", description="Buttery garlic bread", price=80.0)
    m23 = MenuItem(restaurant_id=r2.id, name="Four Cheese", description="Mozzarella, cheddar, parmesan, gouda", price=320.0)
    m24 = MenuItem(restaurant_id=r2.id, name="Veggie Supreme", description="Bell peppers, olives, onions, mushrooms", price=280.0)
    m25 = MenuItem(restaurant_id=r2.id, name="Tiramisu (Dessert)", description="Coffee-flavoured Italian dessert", price=140.0)

    # Sushi House (expanded)
    m8 = MenuItem(restaurant_id=r3.id, name="Salmon Nigiri", description="Fresh salmon over rice", price=180.0)
    m9 = MenuItem(restaurant_id=r3.id, name="California Roll", description="Crab and avocado", price=160.0)
    m10 = MenuItem(restaurant_id=r3.id, name="Miso Soup", description="Warm miso broth", price=60.0)
    m26 = MenuItem(restaurant_id=r3.id, name="Spicy Tuna Roll", description="Tuna with spicy mayo", price=170.0)
    m27 = MenuItem(restaurant_id=r3.id, name="Tempura Prawns", description="Crispy fried prawns", price=210.0)
    m28 = MenuItem(restaurant_id=r3.id, name="Edamame", description="Steamed soybeans with salt", price=70.0)

    # Green Bowl (expanded)
    m11 = MenuItem(restaurant_id=r4.id, name="Quinoa Salad", description="Quinoa, veggies, lemon", price=170.0)
    m12 = MenuItem(restaurant_id=r4.id, name="Grilled Chicken Bowl", description="Protein-packed bowl", price=210.0)
    m13 = MenuItem(restaurant_id=r4.id, name="Smoothie (Berry)", description="Mixed berry smoothie", price=120.0)
    m29 = MenuItem(restaurant_id=r4.id, name="Avocado Toast", description="Sourdough with smashed avocado", price=150.0)
    m30 = MenuItem(restaurant_id=r4.id, name="Kale Caesar", description="Kale, parmesan, light dressing", price=160.0)
    m31 = MenuItem(restaurant_id=r4.id, name="Protein Shake", description="Whey protein with banana", price=130.0)

    # Burger Barn (expanded)
    m14 = MenuItem(restaurant_id=r5.id, name="Classic Burger", description="Beef patty, cheese", price=180.0)
    m15 = MenuItem(restaurant_id=r5.id, name="Fries (Large)", description="Crispy fries", price=70.0)
    m16 = MenuItem(restaurant_id=r5.id, name="Veggie Burger", description="Plant-based patty", price=160.0)
    m32 = MenuItem(restaurant_id=r5.id, name="Double Cheese Burger", description="Two patties, double cheese", price=240.0)
    m33 = MenuItem(restaurant_id=r5.id, name="Onion Rings", description="Crispy battered rings", price=90.0)
    m34 = MenuItem(restaurant_id=r5.id, name="Milkshake (Chocolate)", description="Thick chocolate shake", price=110.0)

    # Taco Fiesta (expanded)
    m17 = MenuItem(restaurant_id=r6.id, name="Chicken Taco", description="Spicy chicken, salsa", price=120.0)
    m18 = MenuItem(restaurant_id=r6.id, name="Beef Burrito", description="Rice, beans, beef", price=190.0)
    m19 = MenuItem(restaurant_id=r6.id, name="Nachos", description="Cheesy nachos", price=140.0)
    m35 = MenuItem(restaurant_id=r6.id, name="Veggie Quesadilla", description="Grilled tortilla with veggies and cheese", price=150.0)
    m36 = MenuItem(restaurant_id=r6.id, name="Churros", description="Fried dough with sugar", price=90.0)
    m37 = MenuItem(restaurant_id=r6.id, name="Salsa & Chips", description="House salsa with tortilla chips", price=80.0)

    db.session.add_all([
        m1,m2,m3,m4,m20,m21,m22,
        m5,m6,m7,m23,m24,m25,
        m8,m9,m10,m26,m27,m28,
        m11,m12,m13,m29,m30,m31,
        m14,m15,m16,m32,m33,m34,
        m17,m18,m19,m35,m36,m37
    ])
    db.session.commit()

    # Demo user and varied orders to seed popularity
    u = User(name="Demo User", email="demo@example.com", password_hash=generate_password_hash("demo123"))
    db.session.add(u); db.session.commit()

    def add_order(user_id, rest, items):
        o = Order(user_id=user_id, restaurant_id=rest.id, total=sum(i['price']*i.get('qty',1) for i in items), status="delivered")
        db.session.add(o); db.session.commit()
        for it in items:
            ol = OrderLine(order_id=o.id, item_id=it['id'], qty=it.get('qty',1), price=it['price'])
            db.session.add(ol)
        db.session.commit()

    # Several orders across restaurants to create realistic popularity counts
    add_order(u.id, r1, [{'id':m1.id,'price':m1.price,'qty':3},{'id':m3.id,'price':m3.price,'qty':2},{'id':m20.id,'price':m20.price,'qty':1}])
    add_order(u.id, r1, [{'id':m2.id,'price':m2.price,'qty':2},{'id':m4.id,'price':m4.price,'qty':1}])
    add_order(u.id, r2, [{'id':m5.id,'price':m5.price,'qty':2},{'id':m24.id,'price':m24.price,'qty':1}])
    add_order(u.id, r2, [{'id':m6.id,'price':m6.price,'qty':1},{'id':m7.id,'price':m7.price,'qty':2}])
    add_order(u.id, r3, [{'id':m8.id,'price':m8.price,'qty':2},{'id':m28.id,'price':m28.price,'qty':1}])
    add_order(u.id, r3, [{'id':m26.id,'price':m26.price,'qty':1},{'id':m27.id,'price':m27.price,'qty':1}])
    add_order(u.id, r4, [{'id':m11.id,'price':m11.price,'qty':2},{'id':m31.id,'price':m31.price,'qty':1}])
    add_order(u.id, r5, [{'id':m14.id,'price':m14.price,'qty':3},{'id':m15.id,'price':m15.price,'qty':2}])
    add_order(u.id, r5, [{'id':m32.id,'price':m32.price,'qty':1},{'id':m34.id,'price':m34.price,'qty':1}])
    add_order(u.id, r6, [{'id':m17.id,'price':m17.price,'qty':2},{'id':m35.id,'price':m35.price,'qty':1}])
    add_order(u.id, r6, [{'id':m18.id,'price':m18.price,'qty':1},{'id':m36.id,'price':m36.price,'qty':2}])

    print("Seeded DB with expanded sample data and richer menus.")

if __name__ == "__main__":
    # Ensure DB creation and seeding run inside the app context
    with app.app_context():
        seed()
    app.run(host="0.0.0.0", port=5000, debug=True)
