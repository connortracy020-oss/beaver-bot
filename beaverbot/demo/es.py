"""Spanish for the sentences the demo's server writes: reviews, reasons something is blocked, results and notes.

The adapters (systems.py) write English. This module turns each English sentence into Spanish just before it is
sent to a browser that asked for Spanish. Doing it here, and not inside the adapters, keeps one copy of the rules
and keeps the stored proposals and history in one language, so the "did anything change since the student read
this?" check compares like with like.

Each rule is an English sentence with {} where a value goes, and its Spanish. {r} marks a value that is itself a
sentence and gets translated too. A sentence with no rule is left in English (a test lists the ones that are
allowed to be: names of classes, people and places, which stay as the systems show them).
"""
import re

RULES = [
    # -- registration: notes and status --------------------------------------------------------------
    ("This term is under way.", "Este trimestre ya empezó."),
    ("Adding and dropping closed after week 1.", "Agregar y dar de baja clases cerró tras la semana 1."),
    ("You can still withdraw from a class through {}, which leaves a W on your transcript.", "Aún puedes retirarte de una clase hasta el {}, lo que deja una W en tu historial."),
    ("Registration is open for you.", "La inscripción está abierta para ti."),
    ("Registration opens for you {}.", "La inscripción abre para ti el {}."),
    ("Until then you can plan and fill your cart.", "Hasta entonces puedes planear y llenar tu carrito."),
    ("Registration for {} hasn't been scheduled yet.", "La inscripción de {} aún no tiene fecha."),
    ("You can plan it now, and your plan carries over.", "Puedes planearlo ahora y tu plan se conserva."),
    ("A hold is blocking registration: {r}.", "Una retención bloquea la inscripción: {r}."),
    ("Book your advisor and the hold comes off after you meet.", "Reserva con tu asesor y la retención se quita después de la reunión."),
    ("Your advising hold is still on until you meet your advisor.", "Tu retención de asesoría sigue hasta que te reúnas con tu asesor."),
    ("You're booked for {} at {}.", "Tienes reunión {} a las {}."),
    ("The hold comes off after that meeting, usually the same day.", "La retención se quita después de esa reunión, normalmente el mismo día."),
    ("Then you can register.", "Después podrás inscribirte."),
    ("See where to pay.", "Mira dónde pagar."),
    ("Registration isn't open for you yet.", "La inscripción aún no abre para ti."),
    ("It opens {}.", "Abre el {}."),
    ("You can plan and fill your cart now, then register in one step when it opens.", "Puedes planear y llenar tu carrito ahora, y luego inscribirte en un paso cuando abra."),
    ("You're not registered yet.", "Aún no tienes clases inscritas."),
    ("Registration is open, so you can register from your cart.", "La inscripción está abierta, así que puedes inscribirte desde tu carrito."),
    ("Registration opens {}.", "La inscripción abre el {}."),
    ("You're not registered: this term is for planning only so far.", "No hay inscripción: por ahora este trimestre es solo para planear."),
    # -- registration: checks --------------------------------------------------------------------------
    ("{} is already in this term.", "{} ya está en este trimestre."),
    ("Swap its section instead of adding it twice.", "Cambia su sección en lugar de agregarla dos veces."),
    ("Your record shows you already passed {}.", "Tu expediente muestra que ya aprobaste {}."),
    ("Retaking it replaces the grade in your GPA but earns no new credit.", "Repetirla reemplaza la nota en tu promedio pero no da créditos nuevos."),
    ("{} needs {} first, which isn't on your record.", "{} requiere antes {}, que no aparece en tu expediente."),
    ("You'd need it done, or an override, before registering.", "Necesitarías tenerla aprobada, o una excepción, antes de inscribirte."),
    ("Take the prerequisite first, or ask the department for an override if you've covered it elsewhere.", "Toma primero el prerrequisito, o pide al departamento una excepción si ya lo cubriste en otro lugar."),
    ("{} has a corequisite ({}) that has to be taken in the same term or earlier.", "{} tiene un correquisito ({}) que debe tomarse en el mismo trimestre o antes."),
    ("Add {} to this term too.", "Agrega también {} a este trimestre."),
    ("This section is restricted: {}.", "Esta sección está restringida: {}."),
    ("If that isn't you, registration will ask for an override.", "Si no es tu caso, la inscripción pedirá una excepción."),
    ("Pick a different section of the same class.", "Elige otra sección de la misma clase."),
    ("It meets at the same time as {} ({}).", "Se cruza con {} ({})."),
    ("The calendar shows the overlap.", "El calendario muestra el cruce."),
    ("Swap one of the two to another section.", "Cambia una de las dos a otra sección."),
    ("{} needs a recitation or lab picked along with the lecture.", "{} necesita una recitación o laboratorio junto con la clase."),
    ("Choose one of its linked sections.", "Elige una de sus secciones enlazadas."),
    ("That makes {} credits.", "Eso suma {} créditos."),
    ("The limit is {} without your college's approval.", "El límite es {} sin la aprobación de tu facultad."),
    ("Remove a class, or ask your advisor about an overload petition.", "Quita una clase, o pregunta a tu asesor por una petición de sobrecarga."),
    ("This section is full right now.", "Esta sección está llena ahora."),
    ("In the real version this opens {} with this filled in, and you finish there.", "En la versión real esto abre {} con los datos listos, y terminas allí."),
    ("No payment happens here.", "Aquí no se hace ningún pago."),
    ("Nothing is sent to an employer.", "No se envía nada a un empleador."),
    ("Pay ${} on myBill", "Pagar ${} en myBill"), ("Sample data: marks the balance as paid, as if you had finished on myBill.", "Datos de muestra: marca el saldo como pagado, como si hubieras terminado en myBill."),
    ("Marked the balance as paid (sample).", "El saldo quedó marcado como pagado (muestra)."),
    ("In the real version you would have paid on {}.", "En la versión real habrías pagado en {}."), ("In the real version you would have applied on Handshake.", "En la versión real habrías postulado en Handshake."),
    ("You don't owe anything this term.", "No debes nada este trimestre."), ("Pay your balance", "Pagar tu saldo"),
    ("Add ${} to {}", "Agregar ${} a {}"), ("Add money to {}", "Agregar dinero a {}"), ("Pick an amount between $5 and $500.", "Elige un monto entre $5 y $500."),
    ("Sample data: adds ${} to your {} balance, as if you had finished on MyCard.", "Datos de muestra: agrega ${} a tu saldo de {}, como si hubieras terminado en MyCard."),
    ("Added ${} to {} (sample).", "Se agregaron ${} a {} (muestra)."), ("Pretend it's added", "Fingir que se agregó"), ("Pretend it's bought", "Fingir que se compró"), ("Pretend I applied", "Fingir que postulé"),
    ("Buy the {} permit for ${}", "Comprar el permiso {} por ${}"), ("Buy the {} permit", "Comprar el permiso {}"),
    ("Sample data: shows the {} permit under your permits, as if you had finished on the parking portal.", "Datos de muestra: muestra el permiso {} entre tus permisos, como si hubieras terminado en el portal de estacionamiento."),
    ("The {} permit shows as bought (sample).", "El permiso {} aparece como comprado (muestra)."), ("You already have that permit.", "Ya tienes ese permiso."),
    ("The {} permit is sold out.", "El permiso {} está agotado."), ("Join its waitlist and you're emailed if one opens up.", "Únete a su lista de espera y te avisan por correo si se libera uno."),
    ("Add a vehicle first.", "Primero agrega un vehículo."), ("Your plate is your permit.", "Tu placa es tu permiso."), ("Add your licence plate, then buy the permit.", "Agrega tu placa y luego compra el permiso."),
    ("You can't get the {} permit.", "No puedes obtener el permiso {}."),
    ("You're an online student, so no annual permit is offered.", "Estudias en línea, así que no se ofrece permiso anual."), ("For a visit to campus, the parking portal sells day permits.", "Para una visita al campus, el portal de estacionamiento vende permisos por día."),
    ("You live in a residence hall, so the Residential permit is the only one you can get.", "Vives en una residencia, así que el permiso Residential es el único que puedes obtener."),
    ("You live off campus, so you can get a commuter permit (A, B or C) or a motorcycle permit.", "Vives fuera del campus, así que puedes obtener un permiso de viajero (A, B o C) o de motocicleta."),
    ("You're an online student, so this is shown for reference: it's for students who come to the Corvallis campus.", "Estudias en línea, así que esto se muestra como referencia: es para estudiantes que van al campus de Corvallis."),
    ("Apply to {}", "Postular a {}"), ("You've already applied to that one.", "Ya postulaste a esa."),
    ("Sample data: marks {} at {} as Applied, as if you had finished on Handshake.", "Datos de muestra: marca {} en {} como Postulado, como si hubieras terminado en Handshake."),
    ("Marked the job as applied (sample).", "El empleo quedó marcado como postulado (muestra)."), ("Nothing was sent to an employer.", "No se envió nada a un empleador."),
    ("Your profile checklist still has {} open.", "En la lista de tu perfil sigue pendiente {}."),
    ("the closest open section {r}.", "la sección con lugar más cercana {r}."),
    ("{} and {} are less than an hour apart on {}.", "{} y {} tienen menos de una hora entre sí el {}."),
    ("{} and {} have a gap of over an hour on {}.", "{} y {} tienen más de una hora entre sí el {}."),
    ("{} is already in your {} classes, so it won't be added again.", "{} ya está en tus clases de {}, así que no se agregará otra vez."),
    ("That {} is full right now.", "Ese grupo de {} está lleno ahora."),
    ("Every open section meets at the same time as a class in this list.", "Todas las secciones con lugar se cruzan con una clase de esta lista."),
    ("Full: puts you on its waitlist (position {}).", "Llena: te pone en su lista de espera (posición {})."),
    ("Can't be registered: {r}", "No se puede inscribir: {r}"),
    ("overlaps {} in your plan", "se cruza con {} en tu plan"), ("overlaps your plan", "se cruza con tu plan"), ("meets in person", "es presencial"), ("is online", "es en línea"),
    ("starts at {}", "empieza a las {}"), ("ends at {}", "termina a las {}"), ("meets {}", "se reúne {}"),
    ("its recitation {r}", "su recitación {r}"), ("its laboratory {r}", "su laboratorio {r}"), ("its lab {r}", "su laboratorio {r}"),
    ("It has a waitlist you can join when you register.", "Tiene una lista de espera a la que puedes unirte al inscribirte."),
    ("It has no waitlist, so pick another section or check back.", "No tiene lista de espera, así que elige otra sección o vuelve a revisar."),
    ("{} is under way, and adding or swapping classes closed after week 1.", "{} ya empezó, y agregar o cambiar clases cerró tras la semana 1."),
    ("A late change needs a Petition for Late Change of Registration from the Registrar.", "Un cambio tardío requiere una Petition for Late Change of Registration del Registrar."),
    # -- registration: reviews --------------------------------------------------------------------------
    ("Add {} to {}", "Agregar {} a {}"),
    ("Add {} to your {} plan", "Agregar {} a tu plan de {}"),
    ("Adds {} as Planned.", "Agrega {} como Planeada."),
    ("Nothing is sent to the registration system.", "No se envía nada al sistema de inscripción."),
    ("Add to plan", "Agregar al plan"),
    ("Add classes to {}", "Agregar clases a {}"),
    ("{} is left out: {r}", "{} queda fuera: {r}"),
    ("Add {} class to your {} plan", "Agregar {} clase a tu plan de {}"),
    ("Add {} classes to your {} plan", "Agregar {} clases a tu plan de {}"),
    ("None of those classes can be added.", "Ninguna de esas clases se puede agregar."),
    ("Add them one at a time from Find a class to pick other sections.", "Agrégalas una por una desde Buscar una clase para elegir otras secciones."),
    ("Remove {}", "Quitar {}"),
    ("You're registered in this class and the term is under way, so it can't just be removed.", "Tienes esta clase inscrita y el trimestre ya empezó, así que no se puede simplemente quitar."),
    ("Withdraw from it instead.", "En su lugar, retírate de ella."),
    ("That leaves a W on your transcript.", "Eso deja una W en tu historial."),
    ("Drop {} from {}", "Dar de baja {} de {}"),
    ("Remove {} from {}", "Quitar {} de {}"),
    ("Drops {}.", "Da de baja {}."),
    ("Removes {}.", "Quita {}."),
    ("Your seat is released.", "Tu lugar queda libre."),
    ("Your other classes stay as they are.", "Tus otras clases quedan como están."),
    ("You lose your place on the waitlist.", "Pierdes tu lugar en la lista de espera."),
    ("No W: the term hasn't started.", "Sin W: el trimestre no ha empezado."),
    ("Nothing was registered, so nothing is dropped.", "No había nada inscrito, así que no se da de baja nada."),
    ("Drop class", "Dar de baja"), ("Remove", "Quitar"),
    ("Swap {}", "Cambiar {}"),
    ("The section you want is full, and swapping would give up your seat in this one.", "La sección que quieres está llena, y cambiar te haría perder tu lugar en esta."),
    ("Stay put, or join that section's waitlist first.", "Quédate donde estás, o únete primero a la lista de espera de esa sección."),
    ("Swap {} to another section", "Cambiar {} a otra sección"),
    ("From {}.", "De {}."), ("To {}.", "A {}."),
    ("It stays {}.", "Sigue {}."),
    ("Swap section", "Cambiar sección"),
    ("Change {}'s linked section", "Cambiar la sección enlazada de {}"),
    ("That recitation or lab is full.", "Esa recitación o laboratorio está llena."),
    ("Pick another one.", "Elige otra."),
    ("Change {}'s {}", "Cambiar {1} de {0}"),
    ("From {} to {}.", "De {} a {}."),
    ("The lecture stays the same.", "La clase principal no cambia."),
    ("Change it", "Cambiarla"),
    ("Move {}", "Mover {}"),
    ("Only a planned class can be moved, and only to a term that hasn't started.", "Solo se puede mover una clase planeada, y solo a un trimestre que no ha empezado."),
    ("Drop or withdraw first if you're registered.", "Si ya te inscribiste, primero da de baja o retírate."),
    ("Move {} to {}", "Mover {} a {}"),
    ("Removes it from {}.", "La quita de {}."),
    ("Adds {} to {} as Planned.", "Agrega {} a {} como Planeada."),
    ("Move it", "Moverla"),
    ("Change how {} is graded", "Cambiar cómo se califica {}"),
    ("This class has only one grading option.", "Esta clase tiene una sola forma de calificación."),
    ("The deadline to change grading for {} was {}.", "La fecha límite para cambiar la calificación de {} fue el {}."),
    ("After that it takes a petition to the Registrar.", "Después de eso se necesita una petición al Registrar."),
    ("An S/U class usually can't count toward your major or minor, and S and U don't affect your GPA.", "Una clase S/U normalmente no cuenta para tu carrera o especialidad, y S y U no afectan tu promedio."),
    ("Check with your advisor first.", "Consulta primero con tu asesor."),
    ("Grade {} as {}", "Calificar {} como {}"),
    ("Changes the grading basis from {} to {}.", "Cambia la forma de calificación de {} a {}."),
    ("The section, time and credits stay the same.", "La sección, el horario y los créditos no cambian."),
    ("Change grading", "Cambiar calificación"),
    ("Pick between {} and {} credits for this class.", "Elige entre {} y {} créditos para esta clase."),
    ("This class has a fixed number of credits.", "Esta clase tiene un número fijo de créditos."),
    ("Change {}'s credits", "Cambiar los créditos de {}"),
    ("Take {} for {} credits", "Tomar {} por {} créditos"),
    ("Changes it from {} to {} credits.", "La cambia de {} a {} créditos."),
    ("The section and time stay the same.", "La sección y el horario no cambian."),
    ("Change credits", "Cambiar créditos"),
    ("Move to cart", "Mover al carrito"),
    ("Only a planned class in a term with registration can go in the cart.", "Solo una clase planeada en un trimestre con inscripción puede ir al carrito."),
    ("Put {} in your cart", "Poner {} en tu carrito"), ("Take {} out of your cart", "Sacar {} de tu carrito"),
    ("{} becomes In cart.", "{} pasa a En el carrito."), ("{} becomes Planned.", "{} pasa a Planeada."),
    ("OK", "Aceptar"),
    ("Withdraw from {}", "Retirarme de {}"),
    ("Withdrawing is for a class you're registered in during a term that has started.", "Retirarse es para una clase inscrita en un trimestre que ya empezó."),
    ("Before a term starts, drop the class instead.", "Antes de que empiece el trimestre, da de baja la clase."),
    ("That leaves no mark.", "Eso no deja ninguna marca."),
    ("The last day to withdraw from a {} class was {}.", "El último día para retirarse de una clase de {} fue el {}."),
    ("After that it takes a Petition for Late Change of Registration, or withdrawing from the whole term.", "Después de eso se necesita una Petition for Late Change of Registration, o retirarse de todo el trimestre."),
    ("A W goes on your transcript.", "Aparece una W en tu historial."),
    ("It doesn't change your GPA.", "No cambia tu promedio."),
    ("There's no tuition refund this late in the term.", "No hay reembolso de matrícula a esta altura del trimestre."),
    ("A withdrawal can't be undone here.", "Un retiro no se puede deshacer aquí."),
    ("Getting back in takes a petition.", "Volver a la clase requiere una petición."),
    ("You'd be at {} credits.", "Quedarías con {} créditos."),
    ("Dropping below 12 credits can change financial aid, scholarships, housing eligibility and, for international students, visa status.",
     "Bajar de 12 créditos puede cambiar tu ayuda financiera, becas, elegibilidad de vivienda y, para estudiantes internacionales, el estatus de visa."),
    ("Check with the Office of Financial Aid or the Office of International Services first.", "Consulta primero con la Office of Financial Aid o la Office of International Services."),
    ("{} becomes Withdrawn with a W.", "{} pasa a Retirada con una W."),
    ("Withdraw", "Retirarme"),
    ("Register for {}", "Inscribirme en {}"),
    ("There's nothing in your cart or plan to register.", "No hay nada en tu carrito ni en tu plan para inscribir."),
    ("Find a class first.", "Primero busca una clase."),
    ("Registers you in {}.", "Te inscribe en {}."),
    ("{} is full: puts you on its waitlist (position {}).", "{} está llena: te pone en su lista de espera (posición {})."),
    ("{} can't be registered: {r}", "{} no se puede inscribir: {r}"),
    ("{} will stay in your cart so you can fix it.", "{} se queda en tu carrito para que lo resuelvas."),
    ("That's {} credits, under the {} that count as full-time.", "Son {} créditos, menos de los {} que cuentan como tiempo completo."),
    ("Classes that fail stay in your cart.", "Las clases que fallen se quedan en tu carrito."),
    ("You can drop a class without a W until the term starts.", "Puedes dar de baja una clase sin W hasta que empiece el trimestre."),
    ("Register", "Inscribirme"),
    ("the section is full and has no waitlist.", "la sección está llena y no tiene lista de espera."),
    # -- registration: results --------------------------------------------------------------------------
    ("Added {} to your {} plan.", "Se agregó {} a tu plan de {}."),
    ("Added {} classes to your {} plan: {}.", "Se agregaron {} clases a tu plan de {}: {}."),
    ("Registered for {}: {}.", "Inscripción en {} hecha: {}."),
    ("Nothing was registered for {}.", "No se inscribió nada para {}."),
    ("{} class didn't go through and stayed in your cart.", "{} clase no pasó y se quedó en tu carrito."),
    ("{} classes didn't go through and stayed in your cart.", "{} clases no pasaron y se quedaron en tu carrito."),
    ("{} was not registered: {r}", "{} no se inscribió: {r}"),
    ("{}: registered.", "{}: inscrita."), ("{}: on the waitlist.", "{}: en lista de espera."),
    ("Dropped {} from {}.", "Se dio de baja {} de {}."),
    ("No W, because the term hasn't started.", "Sin W, porque el trimestre no ha empezado."),
    ("Removed {} from your {} plan.", "Se quitó {} de tu plan de {}."),
    ("Your other classes didn't change.", "Tus otras clases no cambiaron."),
    ("Swapped {} to section {}.", "Se cambió {} a la sección {}."),
    ("It is still {}.", "Sigue {}."),
    ("Changed {}'s linked section to {}.", "Se cambió la sección enlazada de {} a {}."),
    ("The lecture didn't change.", "La clase principal no cambió."),
    ("Moved {} from {} to {}.", "Se movió {} de {} a {}."),
    ("{} will be graded {}.", "{} se calificará {}."),
    ("Nothing else about the class changed.", "Nada más de la clase cambió."),
    ("{} is now {} credits.", "{} ahora es de {} créditos."),
    ("{} is in your cart.", "{} está en tu carrito."), ("{} is back in your plan.", "{} volvió a tu plan."),
    ("Withdrew from {}.", "Te retiraste de {}."),
    ("A W will show on your transcript.", "Aparecerá una W en tu historial."),
    ("This can't be undone here.", "Esto no se puede deshacer aquí."),
    ("Undid: {r}", "Se deshizo: {r}"),
    # -- advising ------------------------------------------------------------------------------------------
    ("Move your meeting with {}", "Mover tu cita con {}"),
    ("Cancels {}.", "Cancela {}."), ("Books {}.", "Reserva {}."),
    ("One step: you don't have to cancel first.", "Un solo paso: no tienes que cancelar primero."),
    ("Move meeting", "Mover cita"),
    ("Book {}", "Reservar con {}"),
    ("An advising hold comes off after you meet, not when you book.", "Una retención de asesoría se quita después de la reunión, no al reservar."),
    ("Book it", "Reservar"),
    ("Cancel your advisor meeting", "Cancelar tu cita con el asesor"),
    ("You don't have a meeting booked.", "No tienes una cita reservada."),
    ("Pick a time to book one.", "Elige un horario para reservar una."),
    ("Cancel your meeting with {}", "Cancelar tu cita con {}"),
    ("Your advising hold stays until you meet, so you'd need a new time before registration opens.", "Tu retención de asesoría sigue hasta que te reúnas, así que necesitarías otro horario antes de que abra la inscripción."),
    ("Cancel meeting", "Cancelar cita"),
    ("Demo only: pretend the meeting happened", "Solo demostración: fingir que la reunión ocurrió"),
    ("Marks the advising meeting as attended.", "Marca la reunión de asesoría como realizada."),
    ("The advising hold comes off, as it would after a real meeting.", "La retención de asesoría se quita, como pasaría tras una reunión real."),
    ("This button exists only so the demo can show what happens next.", "Este botón existe solo para que la demostración muestre lo que sigue."),
    ("Pretend we met", "Fingir que nos reunimos"),
    ("Booked: you're meeting {} {} at {} ({}).", "Reservado: te reúnes con {} {} a las {} ({})."),
    ("Any hold stays until after the meeting.", "Cualquier retención sigue hasta después de la reunión."),
    ("Cancelled your advisor meeting.", "Se canceló tu cita con el asesor."),
    ("Pick a new time whenever you're ready.", "Elige un nuevo horario cuando quieras."),
    ("Marked the advising meeting as attended (demo only).", "Se marcó la reunión de asesoría como realizada (solo demostración)."),
    ("The advising hold is off.", "La retención de asesoría se quitó."),
    ("Book an advising meeting and attend it.", "Reserva una reunión de asesoría y asiste."),
    ("Your advisor removes the hold after you meet, usually the same day.", "Tu asesor quita la retención después de la reunión, normalmente el mismo día."),
    ("Pay the past-due amount, or contact Student Accounts about a payment plan.", "Paga el monto vencido, o contacta a Student Accounts sobre un plan de pagos."),
    ("The hold comes off after the payment posts.", "La retención se quita cuando el pago se registra."),
    ("Send your immunization record to Student Health Services.", "Envía tu registro de vacunas a Student Health Services."),
    ("The hold comes off after they review it.", "La retención se quita después de que lo revisen."),
    ("Advising hold", "Retención de asesoría"), ("advising hold", "retención de asesoría"),
    ("Past-due balance hold", "Retención por saldo vencido"), ("past-due balance hold", "retención por saldo vencido"),
    ("Immunization record missing", "Falta el registro de vacunas"),
    # -- billing ---------------------------------------------------------------------------------------------
    ("A ${} late fee applies to an unpaid balance over $500 after the due date.", "Se cobra un cargo por atraso de ${} a un saldo impago mayor de $500 después de la fecha límite."),
    ("Paying by card adds a 3% fee ($3 minimum).", "Pagar con tarjeta agrega un cargo de 3% (mínimo $3)."),
    ("An eCheck from a bank account has no fee.", "Un eCheck desde una cuenta bancaria no tiene cargo."),
    ("A payment plan costs ${} to join and spreads the term's balance over monthly payments.", "Unirse a un plan de pagos cuesta ${} y reparte el saldo del trimestre en pagos mensuales."),
    ("Payments are made on myBill, OSU's billing site, run by a payment company.", "Los pagos se hacen en myBill, el sitio de cobros de OSU, operado por una empresa de pagos."),
    ("Beaver Bot never sees or asks for a card or bank number.", "Beaver Bot nunca ve ni pide un número de tarjeta o de banco."),
    ("Join a payment plan", "Unirme a un plan de pagos"),
    ("You're already on a payment plan this term.", "Ya tienes un plan de pagos este trimestre."),
    ("You don't owe anything this term, so there's nothing to spread out.", "No debes nada este trimestre, así que no hay nada que repartir."),
    ("Join this term's payment plan", "Unirme al plan de pagos de este trimestre"),
    ("Adds the ${} plan fee to your account.", "Agrega a tu cuenta el cargo de ${} del plan."),
    ("Splits ${} into monthly payments.", "Divide ${} en pagos mensuales."),
    ("No payment is taken now.", "No se cobra nada ahora."),
    ("Payments themselves happen on myBill.", "Los pagos se hacen en myBill."),
    ("While you stay current on the plan, the past-due hold comes off.", "Mientras estés al día con el plan, la retención por saldo vencido se quita."),
    ("Missing a plan payment brings the late fee and the hold back.", "Faltar a un pago del plan trae de vuelta el cargo por atraso y la retención."),
    ("Join the plan", "Unirme al plan"),
    ("Demo only: pretend the balance was paid on myBill", "Solo demostración: fingir que el saldo se pagó en myBill"),
    ("Sets the sample balance to $0.00.", "Pone el saldo de muestra en $0.00."),
    ("A past-due hold comes off.", "Se quita la retención por saldo vencido."),
    ("No payment happens.", "No ocurre ningún pago."),
    ("Beaver Bot has no card or bank form.", "Beaver Bot no tiene formulario de tarjeta ni de banco."),
    ("Pretend it's paid", "Fingir que se pagó"),
    ("You're on this term's payment plan (sample).", "Estás en el plan de pagos de este trimestre (muestra)."),
    ("No payment was taken.", "No se cobró nada."),
    ("The first payment would be made on myBill.", "El primer pago se haría en myBill."),
    ("Marked the balance as paid (demo only).", "Se marcó el saldo como pagado (solo demostración)."),
    ("No payment happened.", "No ocurrió ningún pago."),
    # -- housing ---------------------------------------------------------------------------------------------
    ("For flooding, no heat, a broken lock or anything unsafe, don't file a request: call the hall's front desk or Public Safety now.",
     "Si hay una inundación, falta calefacción, una cerradura rota o algo peligroso, no envíes una solicitud: llama ahora a la recepción de la residencia o a Public Safety."),
    ("File a maintenance request", "Enviar una solicitud de mantenimiento"),
    ("You don't live in a residence hall, so there's no room to file for.", "No vives en una residencia, así que no hay cuarto para el cual pedir."),
    ("Pick where the problem is and describe it in a sentence.", "Elige dónde está el problema y descríbelo en una frase."),
    ("Staff may enter your room to fix it.", "El personal puede entrar a tu cuarto para arreglarlo."),
    ("A confirmation goes to your OSU email.", "Se envía una confirmación a tu correo de OSU."),
    ("Send request", "Enviar solicitud"),
    ("Cancel a request", "Cancelar una solicitud"),
    ("That request isn't open any more.", "Esa solicitud ya no está abierta."),
    ("Cancel this maintenance request", "Cancelar esta solicitud de mantenimiento"),
    ("Cancel request", "Cancelar solicitud"),
    ("Sent the maintenance request (sample).", "Se envió la solicitud de mantenimiento (muestra)."),
    ("Nothing was sent to a real housing office.", "No se envió nada a una oficina de vivienda real."),
    ("Cancelled the maintenance request.", "Se canceló la solicitud de mantenimiento."),
    # -- ID card ---------------------------------------------------------------------------------------------
    ("About ${} a week until the term ends.", "Unos ${} por semana hasta que termine el trimestre."),
    ("No dining plan this term.", "Sin plan de comidas este trimestre."),
    ("Works on and off campus; never expires while you're a student.", "Sirve dentro y fuera del campus; no vence mientras seas estudiante."),
    ("Adding money happens on MyCard with its own payment page.", "Agregar dinero se hace en MyCard, con su propia página de pago."),
    ("Beaver Bot has no card form.", "Beaver Bot no tiene formulario de tarjeta."),
    # -- parking ---------------------------------------------------------------------------------------------
    ("Closest lots, central campus.", "Los estacionamientos más cercanos, en el centro del campus."),
    ("Mid-campus lots and the parking structure.", "Estacionamientos intermedios y el edificio de estacionamiento."),
    ("Edge lots with the campus shuttle.", "Estacionamientos de la orilla, con el autobús del campus."),
    ("For students living in a residence hall.", "Para estudiantes que viven en una residencia."),
    ("Marked motorcycle spaces in any zone.", "Espacios marcados para motocicletas en cualquier zona."),
    ("Buying a permit and paying a citation happen on the parking portal's own payment page.", "Comprar un permiso y pagar una multa se hacen en la página de pago del portal de estacionamiento."),
    ("Join the {} waitlist", "Unirme a la lista de espera de {}"),
    ("That permit isn't sold out, so there's no waitlist.", "Ese permiso no está agotado, así que no hay lista de espera."),
    ("Buy it on the parking portal.", "Cómpralo en el portal de estacionamiento."),
    ("Parking waitlist", "Lista de espera de estacionamiento"),
    ("You're already on that waitlist.", "Ya estás en esa lista de espera."), ("You're not on that waitlist.", "No estás en esa lista de espera."),
    ("Adds you to the waitlist.", "Te agrega a la lista de espera."),
    ("You're emailed if a permit opens up.", "Recibes un correo si se libera un permiso."),
    ("Nothing is charged.", "No se cobra nada."),
    ("You'd still buy the permit yourself if one is offered.", "Si te ofrecen uno, lo comprarías tú."),
    ("You can still buy a different zone meanwhile.", "Mientras tanto puedes comprar otra zona."),
    ("Join waitlist", "Unirme a la lista"),
    ("Leave the {} waitlist", "Salir de la lista de espera de {}"),
    ("Takes you off the waitlist.", "Te saca de la lista de espera."),
    ("Leave waitlist", "Salir de la lista"),
    ("Add a vehicle", "Agregar un vehículo"),
    ("Enter a plate with at least 3 letters or numbers that isn't already listed.", "Escribe una placa de al menos 3 letras o números que no esté ya en la lista."),
    ("Add vehicle {}", "Agregar el vehículo {}"),
    ("Adds plate {} to your parking account.", "Agrega la placa {} a tu cuenta de estacionamiento."),
    ("Your plate is your permit: there's no sticker.", "Tu placa es tu permiso: no hay calcomanía."),
    ("Add vehicle", "Agregar vehículo"),
    ("Remove vehicle {}", "Quitar el vehículo {}"),
    ("Removes plate {}.", "Quita la placa {}."),
    ("You're on the waitlist for {} (sample).", "Estás en la lista de espera de {} (muestra)."),
    ("Nothing was charged.", "No se cobró nada."),
    ("You're off the waitlist for {}.", "Saliste de la lista de espera de {}."),
    ("Added vehicle {}.", "Se agregó el vehículo {}."), ("Removed vehicle {}.", "Se quitó el vehículo {}."),
    # -- careers ---------------------------------------------------------------------------------------------
    ("Applying to a job happens on Handshake, where your resume lives.", "Postular a un empleo se hace en Handshake, donde está tu currículum."),
    ("Save \"{}\"", "Guardar \"{}\""), ("Unsave \"{}\"", "Quitar \"{}\" de guardados"),
    ("Saves it to your saved jobs.", "Lo guarda en tus empleos guardados."), ("Removes it from your saved jobs.", "Lo quita de tus empleos guardados."),
    ("Saving isn't applying.", "Guardar no es postular."), ("The employer isn't told.", "No se le avisa al empleador."),
    ("Save", "Guardar"), ("Unsave", "Quitar"),
    ("Book a career advising appointment", "Reservar una cita de asesoría profesional"),
    ("Books {} with a career advisor.", "Reserva {} con un asesor profesional."),
    ("Replaces the one you have.", "Reemplaza la que tienes."),
    ("Cancel career appointment", "Cancelar cita profesional"),
    ("You don't have one booked.", "No tienes una reservada."),
    ("Cancel your career advising appointment", "Cancelar tu cita de asesoría profesional"),
    ("Cancel it", "Cancelarla"),
    ("Saved the job (sample).", "Se guardó el empleo (muestra)."), ("You haven't applied.", "No has postulado."),
    ("Removed the saved job.", "Se quitó el empleo guardado."),
    ("Booked career advising for {} (sample).", "Se reservó asesoría profesional para {} (muestra)."),
    ("Cancelled the career advising appointment.", "Se canceló la cita de asesoría profesional."),
    ("Upload a resume", "Subir un currículum"), ("Fill in your profile", "Completar tu perfil"), ("Set job preferences", "Elegir preferencias de empleo"),
    # -- library ---------------------------------------------------------------------------------------------
    ("One booking a day, two hours each.", "Una reserva por día, de dos horas."),
    ("Book a study room", "Reservar una sala de estudio"),
    ("You already have a room booked {}.", "Ya tienes una sala reservada {}."),
    ("The limit is one a day.", "El límite es una por día."),
    ("Cancel that one first, or pick another day.", "Cancela esa primero, o elige otro día."),
    ("{} is already taken at {} {}.", "{} ya está ocupada a las {} {}."),
    ("Pick another time or another room.", "Elige otra hora u otra sala."),
    ("Books {} (floor {}, up to {} people) {} at {} for 2 hours.", "Reserva {} (piso {}, hasta {} personas) {} a las {} por 2 horas."),
    ("The room is released if nobody shows up in the first 15 minutes.", "La sala se libera si nadie llega en los primeros 15 minutos."),
    ("Book room", "Reservar sala"),
    ("Cancel a room", "Cancelar una sala"),
    ("That booking isn't there any more.", "Esa reserva ya no existe."),
    ("Cancel {}", "Cancelar {}"),
    ("Cancels {} on {} at {}.", "Cancela {} el {} a las {}."),
    ("Cancel booking", "Cancelar reserva"),
    ("Booked {} {} at {} (sample).", "Se reservó {} {} a las {} (muestra)."),
    ("Cancelled the study room.", "Se canceló la sala de estudio."),
    # -- coursework, degree, health ------------------------------------------------------------------------------
    ("Beaver Bot reads what's due.", "Beaver Bot lee lo que está por entregar."),
    ("It can't see or change grades, and it never submits work.", "No puede ver ni cambiar notas, y nunca entrega trabajos."),
    ("A degree audit is a snapshot.", "Una auditoría de grado es una foto del momento."),
    ("A grade posted or a class added since it last refreshed won't show yet.", "Una nota publicada o una clase agregada desde la última actualización aún no aparece."),
    ("You have an appointment on {}.", "Tienes una cita el {}."),
    ("No upcoming appointments.", "Sin citas próximas."),
    ("Your accommodation letters for this term are ready to send.", "Tus cartas de adaptaciones de este trimestre están listas para enviar."),
    ("Nothing waiting for you.", "Nada pendiente para ti."),
    ("Beaver Bot only shows that something exists and where to see it.", "Beaver Bot solo muestra que algo existe y dónde verlo."),
    ("The details stay in each office's own portal.", "Los detalles se quedan en el portal de cada oficina."),
    # -- to-do items, holds and degree-audit notes from the sample data --------------------------------------
    ("Meet with your advisor", "Reúnete con tu asesor"), ("This clears your advising hold so you can register.", "Esto quita tu retención de asesoría para que puedas inscribirte."),
    ("Complete the pre-registration checklist", "Completa la lista previa a la inscripción"),
    ("Check your holds, your registration time and your {} plan.", "Revisa tus retenciones, tu hora de inscripción y tu plan de {}."),
    ("Confirm your contact information", "Confirma tus datos de contacto"), ("You confirmed your address and phone number.", "Confirmaste tu dirección y teléfono."),
    ("Bring your questions to your advisor meeting", "Lleva tus preguntas a la reunión con tu asesor"),
    ("Your advisor meeting is coming up.", "Tu reunión con el asesor se acerca."), ("Ask how your credits fit a change of major.", "Pregunta cómo encajan tus créditos en un cambio de carrera."),
    ("Pay your next payment plan installment", "Paga la siguiente cuota de tu plan de pagos"), ("The next installment is due in nine days.", "La siguiente cuota vence en nueve días."),
    ("Look at a what-if for {}", "Mira un \"qué pasaría si\" para {}"),
    ("See how the classes you have would count toward a different major.", "Mira cómo contarían tus clases para otra carrera."),
    ("Send your final transcript", "Envía tu historial final"), ("Your transcript from {} arrived.", "Llegó tu historial de {}."),
    ("Pay your past-due balance", "Paga tu saldo vencido"), ("${} was due eight days ago.", "${} venció hace ocho días."), ("Paying it clears your hold.", "Pagarlo quita tu retención."),
    ("Apply to graduate", "Solicita graduarte"), ("You are close to finishing.", "Estás cerca de terminar."),
    ("Apply two terms before your last term.", "Solicítalo dos trimestres antes de tu último trimestre."),
    ("Apply now so your degree can be checked before your last term.", "Solicítalo ahora para que revisen tu título antes de tu último trimestre."),
    ("Update your mailing address", "Actualiza tu dirección postal"), ("You updated your address.", "Actualizaste tu dirección."),
    ("Finish your math placement", "Termina tu ubicación de matemáticas"),
    ("Your placement result decides which math class you can take.", "Tu resultado decide qué clase de matemáticas puedes tomar."),
    ("Meet your advisor", "Reúnete con tu asesor"), ("Your first-year advising meeting is already booked.", "Tu reunión de asesoría de primer año ya está reservada."),
    ("Send your immunization record", "Envía tu registro de vacunas"), ("This clears your health hold.", "Esto quita tu retención de salud."),
    ("Complete new student orientation", "Completa la orientación de nuevos estudiantes"), ("You finished orientation before the term began.", "Terminaste la orientación antes de que empezara el trimestre."),
    ("Talk with your advisor about the class you need to retake", "Habla con tu asesor sobre la clase que debes repetir"),
    ("A D+ does not meet the C or better your major asks for.", "Una D+ no alcanza la C o más que pide tu carrera."), ("Plan the retake for Winter.", "Planea repetirla en invierno."),
    ("Confirm your capstone team", "Confirma tu equipo de proyecto final"), ("Your capstone team was confirmed.", "Tu equipo de proyecto final quedó confirmado."),
    ("Meet with your advisor before registering.", "Reúnete con tu asesor antes de inscribirte."),
    ("Your college asks you to go over your plan with an advisor before Winter registration.", "Tu facultad pide que revises tu plan con un asesor antes de la inscripción de invierno."),
    ("Your account has a past-due balance of ${}.", "Tu cuenta tiene un saldo vencido de ${}."),
    ("You cannot register until it is paid or you set up a payment arrangement.", "No puedes inscribirte hasta pagarlo o acordar un plan de pago."),
    ("Student Health Services does not have your immunization record yet.", "Student Health Services aún no tiene tu registro de vacunas."),
    ("This hold does not stop you from registering for Winter.", "Esta retención no te impide inscribirte para invierno."),
    ("Done", "Hecho"), ("This requirement is complete.", "Este requisito está completo."), ("Nothing to do.", "Nada que hacer."),
    ("Done with transfer credit", "Hecho con crédito transferido"), ("A class you took at another school is counting here.", "Aquí cuenta una clase que tomaste en otra escuela."),
    ("\"Satisfied by\" names that class.", "\"Satisfied by\" indica esa clase."),
    ("In progress", "En curso"), ("You're taking this now.", "La estás tomando ahora."),
    ("It counts once you finish the term with a passing grade.", "Cuenta cuando termines el trimestre con nota aprobatoria."),
    ("In your plan", "En tu plan"), ("You've put this in your sample plan.", "La pusiste en tu plan de muestra."), ("It isn't registered until you register.", "No queda inscrita hasta que te inscribas."),
    ("Still needed", "Aún falta"), ("You haven't taken this yet.", "Aún no la has tomado."), ("It's a to-do, not a problem.", "Es un pendiente, no un problema."),
    ("Still needed: pick from a list", "Aún falta: elige de una lista"), ("You choose which class fills this.", "Tú eliges qué clase lo cumple."),
    ("Any one of the listed classes works, so pick what fits your term.", "Cualquiera de las clases listadas sirve, así que elige la que encaje en tu trimestre."),
    ("Still needed: see section", "Aún falta: ver sección"), ("This line is a bucket of credits, not one class.", "Esta línea es un grupo de créditos, no una sola clase."),
    ("\"See section\" means the list of classes that can fill it is somewhere else on the audit.", "\"See section\" significa que la lista de clases que lo cumplen está en otra parte de la auditoría."),
    ("Your advisor can tell you which of your classes already count.", "Tu asesor puede decirte cuáles de tus clases ya cuentan."),
    ("Minimum grade not met", "Nota mínima no alcanzada"),
    ("You passed this class, but this major needs a C or better in it, so the audit doesn't count it yet.", "Aprobaste esta clase, pero esta carrera pide C o más, así que la auditoría aún no la cuenta."),
    ("It usually means retaking the class.", "Normalmente significa repetir la clase."), ("It does not mean you're in trouble.", "No significa que estés en problemas."),
    ("Bring it to your advisor before you register.", "Coméntalo con tu asesor antes de inscribirte."),
    ("Your GPA lines", "Tus líneas de promedio"), ("The audit shows more than one GPA.", "La auditoría muestra más de un promedio."),
    ("\"Overall\" is every OSU class.", "\"Overall\" son todas las clases de OSU."),
    ("\"Major\" is only the classes in your major, and some majors need it above a set number.", "\"Major\" son solo las clases de tu carrera, y algunas carreras lo piden sobre cierto número."),
    ("A red mark beside a GPA line shows up while any requirement under it is unfinished, even when the number itself is fine.", "Aparece una marca roja junto a un promedio mientras falte algún requisito debajo, aunque el número esté bien."),
    ("This is a snapshot", "Esto es una foto del momento"), ("An audit shows your record as of the last time it was refreshed.", "Una auditoría muestra tu expediente según la última actualización."),
    ("A grade posted or a class added since then won't show until it refreshes.", "Una nota publicada o una clase agregada después no aparece hasta que se actualice."),
    ("Holds cleared", "Retenciones resueltas"), ("No holds are blocking registration.", "Ninguna retención bloquea la inscripción."),
    ("It clears after your meeting {}.", "Se quita después de tu reunión {}."),
    ("Advisor met", "Reunión con el asesor"), ("You've met with your advisor.", "Ya te reuniste con tu asesor."),
    ("No advisor meeting is required for you this term.", "No necesitas reunirte con un asesor este trimestre."),
    ("Booked for {} at {}.", "Reservada para {} a las {}."), ("Book a time with {}.", "Reserva un horario con {}."),
    ("Classes picked", "Clases elegidas"), ("{} class in your plan, {} credits.", "{} clase en tu plan, {} créditos."), ("{} classes in your plan, {} credits.", "{} clases en tu plan, {} créditos."),
    ("Nothing in your winter plan yet.", "Aún no hay nada en tu plan de invierno."), ("Time known", "Hora conocida"),
    ("{}.", "{r}."),
    # -- where data comes from ---------------------------------------------------------------------------------------
    ("the registration system", "el sistema de inscripción"), ("BeaverHub's Success Team", "el Success Team de BeaverHub"),
    ("the parking portal", "el portal de estacionamiento"), ("the library's account and room booking", "la cuenta y las reservas de la biblioteca"),
    ("each office's own portal", "el portal de cada oficina"), ("all connected systems", "todos los sistemas conectados"), ("the class schedule", "el horario de clases"),
    ("the patient portal", "el portal de pacientes"), ("the counseling portal", "el portal de consejería"), ("the DAS portal", "el portal de DAS"),
]

# Small words inside a value: a section's label, a day, a status.
FRAGMENTS = [(re.compile(p), r) for p, r in [
    (r"\bLecture\b", "Clase"), (r"\brecitation\b", "recitación"), (r"\bRecitation\b", "Recitación"), (r"\blab\b", "laboratorio"), (r"\bLab\b", "Laboratorio"),
    (r"(\d (?:AM|PM)) to (\d)", r"\1 a \2"), (r"\bat (\d)", r"a las \1"),
    (r"\bMon\b", "lun"), (r"\bTue\b", "mar"), (r"\bWed\b", "mié"), (r"\bThu\b", "jue"), (r"\bFri\b", "vie"),
    (r"\bMonday\b", "lunes"), (r"\bTuesday\b", "martes"), (r"\bWednesday\b", "miércoles"), (r"\bThursday\b", "jueves"), (r"\bFriday\b", "viernes"),
    (r"\bSaturday\b", "sábado"), (r"\bSunday\b", "domingo"), (r"\btomorrow\b", "mañana"), (r"\bTomorrow\b", "Mañana"), (r"\btoday\b", "hoy"), (r"\bToday\b", "Hoy"),
    (r"\bonline, no set time\b", "en línea, sin horario fijo"), (r"\bOnline, no set time\b", "En línea, sin horario fijo"),
    (r"^Online (\d)", r"En línea \1"), (r"^Laboratory (\d)", r"Laboratorio \1"), (r"^Studio (\d)", r"Taller \1"), (r"\(or an equivalent\)", "(o un equivalente)"),       # ^: the section type that starts a line, never a building's name
    (r"^planned$", "planeada"), (r"^in cart$", "en el carrito"), (r"^registered$", "inscrita"), (r"^waitlisted$", "en lista de espera"),
    (r"^in person$", "en persona"), (r"^phone$", "por teléfono"), (r"\bin person\b", "en persona"), (r"\bminutes\b", "minutos"), (r"^none$", "ninguna"),
    (r"^Normal grading \(A-F\)$", "calificación normal (A-F)"),
]]
# The suggestions under a chat reply. Tapping one sends it as the next message, so each is a whole request.
CHIPS = {"Add the first one": "Agrega la primera", "Any time works": "Cualquier hora me sirve", "Book my advisor": "Reservar con mi asesor",
         "Build my winter plan": "Arma mi plan de invierno", "Find a class": "Busca una clase", "How do I set up a payment plan?": "¿Cómo armo un plan de pagos?",
         "Show my checklist": "Muestra mi lista de pendientes", "Show my plan": "Muestra mi plan", "Try other times": "Prueba otros horarios",
         "What do I still need?": "¿Qué me falta?"}
def chip(text: str) -> str:
    """A suggestion chip in Spanish, including the ones made from a section's time ("Use the 9:00 AM one")."""
    m = re.fullmatch(r"Use the (\d+:\d\d [AP]M) one", text)
    return f"Usa la de las {m.group(1)}" if m else {"Use the online one": "Usa la de en línea"}.get(text, CHIPS.get(text, text))


COURSE_NOTE = re.compile(r"^([A-Z]{2,4} \d{3}[A-Z]?): (.+)$", re.S)
SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"¿¡$])")
# Keys in a response whose values are sentences written by the server.
KEYS = {"title", "effects", "unchanged", "warnings", "reason", "next", "button", "summary", "details", "note", "rules", "rule", "urgent", "limit",
        "line", "snapshot", "source", "zone", "how_to_clear", "portal", "opens_label", "withdraw_label", "detail", "text", "notes", "misses", "bends", "eligibility"}
# Keys whose values are a section's label and meeting time ("Lecture 001 · Tue Thu 8:30 AM to 9:50 AM"): only the small words change.
PARTS = {"times"}


def _compile(english: str) -> re.Pattern:
    parts = re.split(r"(\{r?\})", english)
    return re.compile("".join("(.+?)" if p in ("{}", "{r}") else re.escape(p) for p in parts) + "$", re.S)


# Exact sentences first, then the most specific pattern (the one with the most fixed words) before a looser one,
# so "Cancel request" is never read as "Cancel {}". A sentence that wraps another one ({r}) is tried before the
# sentence it wraps.
_ORDER = sorted(RULES, key=lambda r: ("{" in r[0], "{r}" not in r[0], -len(re.sub(r"\{r?\}", "", r[0]))))
_RULES = [(_compile(en), [p == "{r}" for p in re.findall(r"\{r?\}", en)], es) for en, es in _ORDER]


def fragment(text: str) -> str:
    for rx, to in FRAGMENTS:
        text = rx.sub(to, text)
    return text


def _one(text: str) -> str | None:
    for rx, recursive, spanish in _RULES:
        m = rx.match(text)
        if not m or any(SPLIT.search(g) for g in m.groups()):      # a value never runs across two sentences
            continue
        values = [say(g) if deep else fragment(g) for g, deep in zip(m.groups(), recursive)]
        out, n = spanish, 0
        if re.search(r"\{\d\}", out):
            return out.format(*values)
        for v in values:
            out = out.replace("{r}" if "{r}" in out and recursive[n] else "{}", v, 1)
            n += 1
        return out
    return None


def say(text: str) -> str:
    """One piece of server-written English in Spanish. Tried whole first, then sentence by sentence; a sentence
    with no rule stays as it is."""
    if not isinstance(text, str) or not text.strip():
        return text
    noted = COURSE_NOTE.match(text)             # a note about one class in a list: "CS 261: It meets at the same time as ..."
    if noted:
        return f"{noted.group(1)}: {say(noted.group(2))}"
    whole = _one(text)
    if whole is not None:
        return whole
    parts = SPLIT.split(text)
    if len(parts) == 1:
        return fragment(text) if len(text) < 40 else text
    return " ".join(_one(p) if _one(p) is not None else p for p in parts)


def localize(data):
    """A response for a Spanish page: every server-written sentence translated, everything else untouched."""
    if isinstance(data, list):
        return [localize(x) for x in data]
    if not isinstance(data, dict):
        return data
    out = {}
    for key, value in data.items():
        if key in PARTS and isinstance(value, list):
            out[key] = [fragment(x) if isinstance(x, str) else x for x in value]
        elif key in KEYS and isinstance(value, str):
            out[key] = say(value)
        elif key in KEYS and isinstance(value, list) and all(isinstance(x, str) for x in value):
            out[key] = [say(x) for x in value]
        else:
            out[key] = localize(value)
    return out
