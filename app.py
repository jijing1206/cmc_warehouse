from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pandas as pd
from io import BytesIO
import functools

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cmc-warehouse-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cmc_warehouse.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True

db = SQLAlchemy(app)

# 数据库模型
class SupplierInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_code = db.Column(db.String(50), nullable=False)
    mfg_code = db.Column(db.String(50), nullable=False, unique=True)
    supplier_name = db.Column(db.String(100), nullable=False)
    carrier = db.Column(db.String(100), nullable=False, default='自送')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class InventoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    operation_type = db.Column(db.String(10), nullable=False)  # 'in' or 'out'
    container_type = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    supplier_code = db.Column(db.String(50), nullable=False)
    mfg_code = db.Column(db.String(50), nullable=False)
    supplier_name = db.Column(db.String(100), nullable=False)
    carrier = db.Column(db.String(100), nullable=False, default='自送')
    operator = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text)

class PackingRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    return_date = db.Column(db.Date, nullable=False)
    carrier = db.Column(db.String(100), nullable=False)
    vehicle_type = db.Column(db.String(50), nullable=False)
    driver_name = db.Column(db.String(50), nullable=False)
    driver_phone = db.Column(db.String(20), nullable=False)
    license_plate = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    request_id = db.Column(db.String(20), unique=True)

class PackingRequestItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('packing_request.id'), nullable=False)
    supplier_code = db.Column(db.String(50), nullable=False)
    mfg_code = db.Column(db.String(50), nullable=False)
    supplier_name = db.Column(db.String(100), nullable=False)
    container_type = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    
    # 关联关系
    packing_request = db.relationship('PackingRequest', backref=db.backref('items', lazy=True))

# 模块密码配置
MODULE_PASSWORDS = {
    'registration': 'reg123',      # 入库出库登记
    'inventory': None,             # 库存查询统计 - 去掉密码
    'packing': None,               # 返空装箱申请 - 去掉密码
    'approval': 'app123',          # 申请审批管理
    'system': 'sys123'             # 系统基础设置
}

# 模块权限检查装饰器
def module_required(module_name):
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get(f'{module_name}_access'):
                return redirect(url_for('module_login', module=module_name))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# 移动端检测
def is_mobile():
    user_agent = request.headers.get('User-Agent', '').lower()
    mobile_indicators = ['mobile', 'android', 'iphone', 'ipad', 'ipod']
    return any(indicator in user_agent for indicator in mobile_indicators)

# 首页 - 模块选择
@app.route('/')
def index():
    return render_template('index.html', is_mobile=is_mobile())

# 模块登录
@app.route('/login/<module>', methods=['GET', 'POST'])
def module_login(module):
    if module not in MODULE_PASSWORDS:
        flash('无效的模块', 'error')
        return redirect(url_for('index'))
    
    # 如果模块密码为None，直接跳转到对应页面
    if MODULE_PASSWORDS[module] is None:
        if module == 'inventory':
            return redirect(url_for('inventory'))
        elif module == 'packing':
            return redirect(url_for('packing_request'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        if password == MODULE_PASSWORDS[module]:
            session[f'{module}_access'] = True
            # 根据模块跳转到对应页面
            if module == 'registration':
                return redirect(url_for('registration'))
            elif module == 'inventory':
                return redirect(url_for('inventory'))
            elif module == 'packing':
                return redirect(url_for('packing_request'))
            elif module == 'approval':
                return redirect(url_for('approval'))
            elif module == 'system':
                return redirect(url_for('system_settings'))
        else:
            flash('密码错误', 'error')
    
    module_names = {
        'registration': '入库出库登记',
        'inventory': '库存查询统计', 
        'packing': '返空装箱申请',
        'approval': '申请审批管理',
        'system': '系统基础设置'
    }
    
    return render_template('login.html', 
                         module=module, 
                         module_name=module_names.get(module, '未知模块'),
                         is_mobile=is_mobile())

# 模块退出
@app.route('/logout/<module>')
def module_logout(module):
    session.pop(f'{module}_access', None)
    flash('已退出模块', 'info')
    return redirect(url_for('index'))

# 获取供应商信息
@app.route('/api/supplier-info/<mfg_code>')
def get_supplier_info(mfg_code):
    supplier = SupplierInfo.query.filter_by(mfg_code=mfg_code).first()
    if supplier:
        return jsonify({
            'supplier_code': supplier.supplier_code,
            'supplier_name': supplier.supplier_name,
            'carrier': supplier.carrier
        })
    else:
        return jsonify({'error': '未找到该发货地代码对应的供应商信息'}), 404

# 入库出库登记模块
@app.route('/registration', methods=['GET', 'POST'])
@module_required('registration')
def registration():
    if request.method == 'POST':
        operation_type = request.form.get('operation_type')
        container_type = request.form.get('container_type')
        quantity = request.form.get('quantity')
        mfg_code = request.form.get('mfg_code')
        notes = request.form.get('notes')
        
        if not all([operation_type, container_type, quantity, mfg_code]):
            flash('请填写所有必填字段', 'error')
            return redirect(url_for('registration'))
        
        # 获取供应商信息
        supplier = SupplierInfo.query.filter_by(mfg_code=mfg_code).first()
        if not supplier:
            flash('未找到该发货地代码对应的供应商信息，请检查代码或联系管理员', 'error')
            return redirect(url_for('registration'))
        
        # 创建库存记录
        inventory_log = InventoryLog(
            operation_type=operation_type,
            container_type=container_type,
            quantity=int(quantity),
            supplier_code=supplier.supplier_code,
            mfg_code=mfg_code,
            supplier_name=supplier.supplier_name,
            carrier=supplier.carrier,
            operator='登记员',
            notes=notes
        )
        
        db.session.add(inventory_log)
        db.session.commit()
        
        operation_text = '入库' if operation_type == 'in' else '出库'
        flash(f'{operation_text}登记成功！数量：{quantity}', 'success')
        return redirect(url_for('registration'))
    
    container_types = ['塑箱', '铁料架', '桶', '围板箱']
    
    return render_template('registration.html',
                         container_types=container_types,
                         is_mobile=is_mobile())

# 库存查询统计模块 - 去掉权限检查
@app.route('/inventory')
def inventory():
    # 获取筛选参数
    carrier_filter = request.args.get('carrier')
    supplier_filter = request.args.get('supplier')
    container_type_filter = request.args.get('container_type')
    
    # 构建基础查询 - 优化查询性能
    query = db.session.query(
        InventoryLog.supplier_code,
        InventoryLog.mfg_code,
        InventoryLog.supplier_name,
        InventoryLog.carrier,
        InventoryLog.container_type,
        db.func.sum(
            db.case(
                (InventoryLog.operation_type == 'in', InventoryLog.quantity),
                else_=0
            )
        ).label('total_in'),
        db.func.sum(
            db.case(
                (InventoryLog.operation_type == 'out', InventoryLog.quantity),
                else_=0
            )
        ).label('total_out')
    ).group_by(
        InventoryLog.supplier_code,
        InventoryLog.mfg_code,
        InventoryLog.supplier_name, 
        InventoryLog.carrier, 
        InventoryLog.container_type
    )
    
    # 应用筛选条件
    if carrier_filter:
        query = query.filter(InventoryLog.carrier == carrier_filter)
    if supplier_filter:
        query = query.filter(
            (InventoryLog.supplier_code.contains(supplier_filter)) |
            (InventoryLog.mfg_code.contains(supplier_filter)) |
            (InventoryLog.supplier_name.contains(supplier_filter))
        )
    if container_type_filter:
        query = query.filter(InventoryLog.container_type == container_type_filter)
    
    inventory_data = query.all()
    
    # 计算当前库存
    inventory_results = []
    for item in inventory_data:
        current_stock = item.total_in - item.total_out
        if current_stock > 0:
            inventory_results.append({
                'supplier_code': item.supplier_code,
                'mfg_code': item.mfg_code,
                'supplier_name': item.supplier_name,
                'carrier': item.carrier,
                'container_type': item.container_type,
                'current_stock': current_stock
            })
    
    container_types = ['塑箱', '铁料架', '桶', '围板箱']
    carriers = ['中世', '中邮', '瑞源', '安吉', '风神', '自送']
    
    return render_template('inventory.html', 
                         inventory=inventory_results,
                         container_types=container_types,
                         carriers=carriers,
                         is_mobile=is_mobile())

# 返空装箱申请模块 - 去掉权限检查
@app.route('/packing', methods=['GET', 'POST'])
def packing_request():
    if request.method == 'POST':
        return_date = request.form.get('return_date')
        vehicle_type = request.form.get('vehicle_type')
        driver_name = request.form.get('driver_name')
        driver_phone = request.form.get('driver_phone')
        license_plate = request.form.get('license_plate')
        carrier = request.form.get('carrier')
        
        # 获取动态添加的物品数据
        mfg_codes = request.form.getlist('mfg_code[]')
        container_types = request.form.getlist('container_type[]')
        quantities = request.form.getlist('quantity[]')
        
        if not all([return_date, vehicle_type, driver_name, driver_phone, license_plate, carrier]):
            flash('请填写所有必填字段', 'error')
            return redirect(url_for('packing_request'))
        
        if not mfg_codes:
            flash('请至少添加一个物品', 'error')
            return redirect(url_for('packing_request'))
        
        # 验证库存数量
        for i, mfg_code in enumerate(mfg_codes):
            container_type = container_types[i]
            quantity = int(quantities[i])
            
            supplier = SupplierInfo.query.filter_by(mfg_code=mfg_code).first()
            if not supplier:
                flash(f'未找到发货地代码 {mfg_code} 对应的供应商信息', 'error')
                return redirect(url_for('packing_request'))
            
            current_stock = get_mfg_inventory(mfg_code, container_type)
            if quantity > current_stock:
                flash(f'申请数量({quantity})超过当前库存({current_stock})，请调整数量', 'error')
                return redirect(url_for('packing_request'))
        
        # 生成申请单号
        request_id = f"REQ{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 创建装箱需求主表
        packing_request = PackingRequest(
            return_date=datetime.strptime(return_date, '%Y-%m-%d').date(),
            carrier=carrier,
            vehicle_type=vehicle_type,
            driver_name=driver_name,
            driver_phone=driver_phone,
            license_plate=license_plate,
            request_id=request_id
        )
        
        db.session.add(packing_request)
        db.session.flush()  # 获取主表ID
        
        # 创建物品明细
        for i, mfg_code in enumerate(mfg_codes):
            container_type = container_types[i]
            quantity = int(quantities[i])
            
            supplier = SupplierInfo.query.filter_by(mfg_code=mfg_code).first()
            
            request_item = PackingRequestItem(
                request_id=packing_request.id,
                supplier_code=supplier.supplier_code,
                mfg_code=mfg_code,
                supplier_name=supplier.supplier_name,
                container_type=container_type,
                quantity=quantity
            )
            db.session.add(request_item)
        
        db.session.commit()
        
        flash(f'装箱需求提交成功！申请单号：<strong>{request_id}</strong>，请妥善保存以便查询', 'success')
        return redirect(url_for('packing_request'))
    
    container_types = ['塑箱', '铁料架', '桶', '围板箱']
    carriers = ['中世', '中邮', '瑞源', '安吉', '风神', '自送']
    
    return render_template('packing_request.html',
                         container_types=container_types,
                         carriers=carriers,
                         is_mobile=is_mobile())

# 申请状态查询（无需登录即可访问）
@app.route('/check-request', methods=['GET', 'POST'])
def check_request():
    request_id = request.form.get('request_id') if request.method == 'POST' else request.args.get('request_id')
    license_plate = request.form.get('license_plate') if request.method == 'POST' else request.args.get('license_plate')
    driver_name = request.form.get('driver_name') if request.method == 'POST' else request.args.get('driver_name')
    
    request_info = None
    
    if request.method == 'POST' or request.args:
        if request_id:
            request_info = PackingRequest.query.filter_by(request_id=request_id).first()
        elif license_plate and driver_name:
            request_info = PackingRequest.query.filter_by(
                license_plate=license_plate, 
                driver_name=driver_name
            ).order_by(PackingRequest.request_date.desc()).first()
        
        if not request_info:
            flash('未找到匹配的申请信息', 'error')
    
    return render_template('check_request.html', 
                         request_id=request_id,
                         license_plate=license_plate,
                         driver_name=driver_name,
                         request_info=request_info,
                         is_mobile=is_mobile())

# 申请审批管理模块
@app.route('/approval')
@module_required('approval')
def approval():
    status_filter = request.args.get('status', 'pending')
    
    query = PackingRequest.query
    
    if status_filter != 'all':
        query = query.filter(PackingRequest.status == status_filter)
    
    packing_requests = query.order_by(PackingRequest.request_date.desc()).all()
    
    return render_template('approval.html',
                         packing_requests=packing_requests,
                         status_filter=status_filter,
                         is_mobile=is_mobile())

# 更新申请状态
@app.route('/update-request/<int:request_id>', methods=['POST'])
@module_required('approval')
def update_request(request_id):
    packing_request = PackingRequest.query.get_or_404(request_id)
    new_status = request.form.get('status')
    
    if new_status in ['pending', 'approved', 'completed']:
        packing_request.status = new_status
        db.session.commit()
        flash('申请状态更新成功！', 'success')
    
    return redirect(url_for('approval'))

# 系统基础设置模块
@app.route('/system')
@module_required('system')
def system_settings():
    # 统计信息
    stats = {
        'total_requests': PackingRequest.query.count(),
        'pending_requests': PackingRequest.query.filter_by(status='pending').count(),
        'today_logs': InventoryLog.query.filter(
            db.func.date(InventoryLog.timestamp) == datetime.today().date()
        ).count(),
        'supplier_count': SupplierInfo.query.count()
    }
    
    # 获取所有供应商信息
    suppliers = SupplierInfo.query.order_by(SupplierInfo.supplier_code, SupplierInfo.mfg_code).all()
    
    return render_template('system.html', 
                         stats=stats, 
                         suppliers=suppliers,
                         is_mobile=is_mobile())

# 添加供应商信息
@app.route('/system/add-supplier', methods=['POST'])
@module_required('system')
def add_supplier():
    supplier_code = request.form.get('supplier_code')
    mfg_code = request.form.get('mfg_code')
    supplier_name = request.form.get('supplier_name')
    carrier = request.form.get('carrier')
    
    if not all([supplier_code, mfg_code, supplier_name, carrier]):
        flash('请填写所有必填字段', 'error')
        return redirect(url_for('system_settings'))
    
    # 检查MFG代码是否已存在
    if SupplierInfo.query.filter_by(mfg_code=mfg_code).first():
        flash('该发货地代码已存在', 'error')
        return redirect(url_for('system_settings'))
    
    supplier = SupplierInfo(
        supplier_code=supplier_code,
        mfg_code=mfg_code,
        supplier_name=supplier_name,
        carrier=carrier
    )
    
    db.session.add(supplier)
    db.session.commit()
    
    flash('供应商信息添加成功！', 'success')
    return redirect(url_for('system_settings'))

# 编辑供应商信息
@app.route('/system/edit-supplier/<int:supplier_id>', methods=['POST'])
@module_required('system')
def edit_supplier(supplier_id):
    supplier = SupplierInfo.query.get_or_404(supplier_id)
    
    supplier_code = request.form.get('supplier_code')
    mfg_code = request.form.get('mfg_code')
    supplier_name = request.form.get('supplier_name')
    carrier = request.form.get('carrier')
    
    if not all([supplier_code, mfg_code, supplier_name, carrier]):
        flash('请填写所有必填字段', 'error')
        return redirect(url_for('system_settings'))
    
    # 检查MFG代码是否与其他供应商冲突
    existing_supplier = SupplierInfo.query.filter(
        SupplierInfo.mfg_code == mfg_code,
        SupplierInfo.id != supplier_id
    ).first()
    
    if existing_supplier:
        flash('该发货地代码已存在', 'error')
        return redirect(url_for('system_settings'))
    
    supplier.supplier_code = supplier_code
    supplier.mfg_code = mfg_code
    supplier.supplier_name = supplier_name
    supplier.carrier = carrier
    
    db.session.commit()
    
    flash('供应商信息更新成功！', 'success')
    return redirect(url_for('system_settings'))

# 删除供应商信息
@app.route('/system/delete-supplier/<int:supplier_id>', methods=['POST'])
@module_required('system')
def delete_supplier(supplier_id):
    supplier = SupplierInfo.query.get_or_404(supplier_id)
    
    # 检查是否有相关的库存记录
    if InventoryLog.query.filter_by(mfg_code=supplier.mfg_code).first():
        flash('该供应商已有库存记录，无法删除', 'error')
        return redirect(url_for('system_settings'))
    
    db.session.delete(supplier)
    db.session.commit()
    
    flash('供应商信息删除成功！', 'success')
    return redirect(url_for('system_settings'))

# 导出库存为Excel
@app.route('/system/export-inventory')
@module_required('system')
def export_inventory():
    # 获取所有库存数据
    inventory_data = db.session.query(
        InventoryLog.supplier_code,
        InventoryLog.mfg_code,
        InventoryLog.supplier_name,
        InventoryLog.carrier,
        InventoryLog.container_type,
        db.func.sum(
            db.case(
                (InventoryLog.operation_type == 'in', InventoryLog.quantity),
                else_=0
            )
        ).label('total_in'),
        db.func.sum(
            db.case(
                (InventoryLog.operation_type == 'out', InventoryLog.quantity),
                else_=0
            )
        ).label('total_out')
    ).group_by(
        InventoryLog.supplier_code,
        InventoryLog.mfg_code,
        InventoryLog.supplier_name, 
        InventoryLog.carrier, 
        InventoryLog.container_type
    ).all()
    
    # 转换为DataFrame
    data = []
    for item in inventory_data:
        current_stock = item.total_in - item.total_out
        if current_stock > 0:
            data.append({
                '供应商代码': item.supplier_code,
                '发货地代码': item.mfg_code,
                '供应商名称': item.supplier_name,
                '承运商': item.carrier,
                '空器具类型': item.container_type,
                '当前库存': current_stock
            })
    
    if not data:
        flash('没有可导出的库存数据', 'error')
        return redirect(url_for('system_settings'))
    
    df = pd.DataFrame(data)
    
    # 创建Excel文件
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='库存数据', index=False)
    
    output.seek(0)
    
    # 生成文件名
    filename = f'CMC库存数据_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    
    return output.getvalue(), 200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': f'attachment; filename={filename}'
    }

# 导出入库记录
@app.route('/system/export-inventory-logs')
@module_required('system')
def export_inventory_logs():
    # 获取筛选参数
    operation_type = request.args.get('operation_type')
    container_type = request.args.get('container_type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    supplier = request.args.get('supplier')
    
    # 构建查询
    query = InventoryLog.query
    
    if operation_type:
        query = query.filter(InventoryLog.operation_type == operation_type)
    if container_type:
        query = query.filter(InventoryLog.container_type == container_type)
    if date_from:
        query = query.filter(InventoryLog.timestamp >= datetime.strptime(date_from, '%Y-%m-%d'))
    if date_to:
        # 结束日期包含一整天
        end_date = datetime.strptime(date_to, '%Y-%m-%d')
        end_date = end_date.replace(hour=23, minute=59, second=59)
        query = query.filter(InventoryLog.timestamp <= end_date)
    if supplier:
        query = query.filter(
            (InventoryLog.supplier_code.contains(supplier)) |
            (InventoryLog.mfg_code.contains(supplier)) |
            (InventoryLog.supplier_name.contains(supplier))
        )
    
    logs = query.order_by(InventoryLog.timestamp.desc()).all()
    
    # 转换为DataFrame
    data = []
    for log in logs:
        data.append({
            '时间': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            '操作类型': '入库' if log.operation_type == 'in' else '出库',
            '空器具类型': log.container_type,
            '数量': log.quantity,
            '供应商代码': log.supplier_code,
            '发货地代码': log.mfg_code,
            '供应商名称': log.supplier_name,
            '承运商': log.carrier,
            '操作员': log.operator,
            '备注': log.notes or ''
        })
    
    if not data:
        flash('没有可导出的操作记录', 'error')
        return redirect(url_for('system_settings'))
    
    df = pd.DataFrame(data)
    
    # 创建Excel文件
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='出入库记录', index=False)
    
    output.seek(0)
    
    # 生成文件名
    filename = f'CMC出入库记录_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    
    return output.getvalue(), 200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': f'attachment; filename={filename}'
    }

# 获取特定MFG代码的库存（用于前端验证）
@app.route('/api/stock/<mfg_code>/<container_type>')
def get_stock(mfg_code, container_type):
    # 计算入库总量
    in_total = db.session.query(db.func.sum(InventoryLog.quantity)).filter(
        InventoryLog.mfg_code == mfg_code,
        InventoryLog.container_type == container_type,
        InventoryLog.operation_type == 'in'
    ).scalar() or 0
    
    # 计算出库总量
    out_total = db.session.query(db.func.sum(InventoryLog.quantity)).filter(
        InventoryLog.mfg_code == mfg_code,
        InventoryLog.container_type == container_type,
        InventoryLog.operation_type == 'out'
    ).scalar() or 0
    
    return jsonify({'current_stock': in_total - out_total})

# 辅助函数：获取特定MFG代码的库存
def get_mfg_inventory(mfg_code, container_type):
    # 计算入库总量
    in_total = db.session.query(db.func.sum(InventoryLog.quantity)).filter(
        InventoryLog.mfg_code == mfg_code,
        InventoryLog.container_type == container_type,
        InventoryLog.operation_type == 'in'
    ).scalar() or 0
    
    # 计算出库总量
    out_total = db.session.query(db.func.sum(InventoryLog.quantity)).filter(
        InventoryLog.mfg_code == mfg_code,
        InventoryLog.container_type == container_type,
        InventoryLog.operation_type == 'out'
    ).scalar() or 0
    
    return in_total - out_total

# 初始化供应商数据
def init_supplier_data():
    # 添加一些示例数据
    if SupplierInfo.query.count() == 0:
        sample_suppliers = [
            {'supplier_code': '1ME', 'mfg_code': '1ME-1', 'supplier_name': '博世汽车部件（苏州）有限公司', 'carrier': '中世'},
            {'supplier_code': '1ME', 'mfg_code': '1ME-2', 'supplier_name': '博世汽车部件（苏州）有限公司', 'carrier': '中邮'},
            {'supplier_code': '8MH', 'mfg_code': '8MH-2', 'supplier_name': '芜湖新泉', 'carrier': '瑞源'},
            {'supplier_code': '8MH', 'mfg_code': '8MH-3', 'supplier_name': '常州新泉', 'carrier': '安吉'},
        ]
        
        for supplier_data in sample_suppliers:
            supplier = SupplierInfo(**supplier_data)
            db.session.add(supplier)
        
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_supplier_data()
    app.run(debug=False)